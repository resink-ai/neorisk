// Kernels for the restructured v3 forward pass, compiled at run time with NVRTC.
// Every kernel exists for float (precision mode) and fp16 (recall mode) activations; all
// arithmetic accumulates in float, LayerNorm and bias parameters stay float. fp16 values are
// raw 16-bit words converted with PTX cvt, so no CUDA headers are needed at run time.

typedef unsigned short half_t;
#define NEG_INF __int_as_float(0xff800000)

template <typename T> __device__ __forceinline__ float ld(const T* p);
template <> __device__ __forceinline__ float ld<float>(const float* p) { return *p; }
template <> __device__ __forceinline__ float ld<half_t>(const half_t* p) {
    float f;
    asm("cvt.f32.f16 %0, %1;" : "=f"(f) : "h"(*p));
    return f;
}
template <typename T> __device__ __forceinline__ void st(T* p, float v);
template <> __device__ __forceinline__ void st<float>(float* p, float v) { *p = v; }
template <> __device__ __forceinline__ void st<half_t>(half_t* p, float v) {
    half_t h;
    asm("cvt.rn.f16.f32 %0, %1;" : "=h"(h) : "f"(v));
    *p = h;
}

__device__ __forceinline__ float warp_sum(float v) {
    for (int o = 16; o > 0; o >>= 1) v += __shfl_xor_sync(0xffffffff, v, o);
    return v;
}
__device__ __forceinline__ float warp_max(float v) {
    for (int o = 16; o > 0; o >>= 1) v = fmaxf(v, __shfl_xor_sync(0xffffffff, v, o));
    return v;
}

// Table element i (flat) as float: fp32, fp16, or int8 with one scale per d-wide chunk.
__device__ __forceinline__ float tval(const float* t, const float*, long i, int) { return t[i]; }
__device__ __forceinline__ float tval(const half_t* t, const float*, long i, int) { return ld(t + i); }
__device__ __forceinline__ float tval(const signed char* t, const float* s, long i, int d) {
    return (float)t[i] * s[i / d];
}

// Row r = p*L + j of x (width d) and, if with_qkv, qkv (width 3d): CLS for j == 0, else the
// precomputed token row of field j-1. One block per row. Scales are only read for int8 tables.
template <typename TT, typename T>
__device__ void gather(const int* codes, int nf, const int* field_idx, const int* offsets, int L,
                       const TT* tok, const float* tok_s, const TT* qkv1, const float* qkv1_s,
                       const TT* cls_tok, const float* ct_s, const TT* cls_qkv1, const float* cq_s,
                       int d, T* x, T* qkv, int with_qkv) {
    int r = blockIdx.x, p = r / L, j = r % L;
    const TT *src_x = cls_tok, *src_q = cls_qkv1;
    const float *sx = ct_s, *sq = cq_s;
    long v = 0;
    if (j > 0) {
        v = (long)codes[(long)p * nf + field_idx[j - 1]] + offsets[j - 1];
        src_x = tok;
        src_q = qkv1;
        sx = tok_s;
        sq = qkv1_s;
    }
    for (int c = threadIdx.x; c < d; c += blockDim.x) st(x + (long)r * d + c, tval(src_x, sx, v * d + c, d));
    if (with_qkv)
        for (int c = threadIdx.x; c < 3 * d; c += blockDim.x)
            st(qkv + (long)r * 3 * d + c, tval(src_q, sq, v * 3 * d + c, d));
}

// Full self-attention for one (profile, head): grid (B, heads), one thread per query row,
// K and V of the head staged in shared memory, online (single-pass) softmax per query.
template <typename T, int DH>
__device__ void attention_full(const T* qkv, T* out, int L, int d) {
    extern __shared__ float sh[];
    float* K = sh;
    float* V = sh + L * DH;
    int p = blockIdx.x, h = blockIdx.y, w = 3 * d;
    const T* base = qkv + (long)p * L * w;
    for (int e = threadIdx.x; e < L * DH; e += blockDim.x) {
        int j = e / DH, c = e % DH;
        K[e] = ld(base + (long)j * w + d + h * DH + c);
        V[e] = ld(base + (long)j * w + 2 * d + h * DH + c);
    }
    __syncthreads();
    int i = threadIdx.x;
    if (i >= L) return;
    const float scale = rsqrtf((float)DH);
    float q[DH], acc[DH];
#pragma unroll
    for (int c = 0; c < DH; c++) {
        q[c] = ld(base + (long)i * w + h * DH + c) * scale;
        acc[c] = 0.f;
    }
    float m = NEG_INF, sum = 0.f;
    for (int j = 0; j < L; j++) {
        float s = 0.f;
#pragma unroll
        for (int c = 0; c < DH; c++) s = fmaf(q[c], K[j * DH + c], s);
        float mn = fmaxf(m, s);
        float corr = __expf(m - mn), e = __expf(s - mn);
        sum = sum * corr + e;
#pragma unroll
        for (int c = 0; c < DH; c++) acc[c] = fmaf(e, V[j * DH + c], acc[c] * corr);
        m = mn;
    }
    float inv = 1.f / sum;
    T* o = out + ((long)p * L + i) * d + h * DH;
#pragma unroll
    for (int c = 0; c < DH; c++) st(o + c, acc[c] * inv);
}

// Attention of the CLS query over the profile's L keys: grid (B), one warp per head.
template <typename T, int DH>
__device__ void attention_cls(const T* q, const T* kv, T* out, int L, int d) {
    int p = blockIdx.x, h = threadIdx.x / 32, lane = threadIdx.x % 32, w = 2 * d;
    const float scale = rsqrtf((float)DH);
    float qv[DH];
#pragma unroll
    for (int c = 0; c < DH; c++) qv[c] = ld(q + (long)p * d + h * DH + c) * scale;
    const T* base = kv + (long)p * L * w;
    float m = NEG_INF, sum = 0.f, acc[DH];
#pragma unroll
    for (int c = 0; c < DH; c++) acc[c] = 0.f;
    for (int j = lane; j < L; j += 32) {
        float s = 0.f;
#pragma unroll
        for (int c = 0; c < DH; c++) s = fmaf(qv[c], ld(base + (long)j * w + h * DH + c), s);
        float mn = fmaxf(m, s);
        float corr = __expf(m - mn), e = __expf(s - mn);
        sum = sum * corr + e;
#pragma unroll
        for (int c = 0; c < DH; c++) acc[c] = fmaf(e, ld(base + (long)j * w + d + h * DH + c), acc[c] * corr);
        m = mn;
    }
    // merge the lanes' partial softmax states
    float gm = warp_max(m);
    float corr = (m == NEG_INF) ? 0.f : __expf(m - gm);
    float total = warp_sum(sum * corr);
#pragma unroll
    for (int c = 0; c < DH; c++) acc[c] = warp_sum(acc[c] * corr);
    if (lane == 0) {
        float inv = 1.f / total;
        for (int c = 0; c < DH; c++) st(out + (long)p * d + h * DH + c, acc[c] * inv);
    }
}

// y = LayerNorm(x) per row, one warp per row; x rows are ld_in apart (CLS rows: L*d).
template <typename T>
__device__ void layer_norm(const T* x, int ld_in, T* y, const float* w, const float* b, int rows, int d, float eps) {
    int r = blockIdx.x * (blockDim.x / 32) + threadIdx.x / 32, lane = threadIdx.x % 32;
    if (r >= rows) return;
    const T* xr = x + (long)r * ld_in;
    float v[2] = {0.f, 0.f};  // d <= 64
    float s = 0.f;
    for (int k = 0; k < 2; k++) {
        int c = lane + 32 * k;
        if (c < d) { v[k] = ld(xr + c); s += v[k]; }
    }
    float mean = warp_sum(s) / d, var = 0.f;
    for (int k = 0; k < 2; k++) {
        int c = lane + 32 * k;
        if (c < d) var += (v[k] - mean) * (v[k] - mean);
    }
    float rstd = rsqrtf(warp_sum(var) / d + eps);
    for (int k = 0; k < 2; k++) {
        int c = lane + 32 * k;
        if (c < d) st(y + (long)r * d + c, (v[k] - mean) * rstd * w[c] + b[c]);
    }
}

// x[r, c] += bias[c] (then ReLU), rows of width n with stride ld.
template <typename T>
__device__ void bias_act(T* x, int ldx, const float* bias, int n, long total, int relu) {
    long e = (long)blockIdx.x * blockDim.x + threadIdx.x;
    if (e >= total) return;
    long r = e / n;
    int c = e % n;
    float v = ld(x + r * ldx + c) + bias[c];
    st(x + r * ldx + c, relu ? fmaxf(v, 0.f) : v);
}

// c[p] = x[p * L] (the CLS rows), width d.
template <typename T>
__device__ void take_cls(const T* x, T* c, int L, int d, long total) {
    long e = (long)blockIdx.x * blockDim.x + threadIdx.x;
    if (e >= total) return;
    long p = e / d;
    c[e] = x[p * L * d + e % d];
}

// out[p, col + c] = scale * y[p, c] / ||y[p]||, one warp per row, out in float.
template <typename T>
__device__ void finish(const T* y, int n, float* out, int dim, int col, float scale, int rows) {
    int r = blockIdx.x * (blockDim.x / 32) + threadIdx.x / 32, lane = threadIdx.x % 32;
    if (r >= rows) return;
    float s = 0.f;
    for (int c = lane; c < n; c += 32) { float v = ld(y + (long)r * n + c); s += v * v; }
    float k = scale / fmaxf(sqrtf(warp_sum(s)), 1e-12f);
    for (int c = lane; c < n; c += 32) out[(long)r * dim + col + c] = ld(y + (long)r * n + c) * k;
}


// Softmax of each row of s (rows of length L, already scaled), one warp per row.
template <typename T>
__device__ void softmax_rows(T* s, long rows, int L) {
    long r = (long)blockIdx.x * (blockDim.x / 32) + threadIdx.x / 32;
    int lane = threadIdx.x % 32;
    if (r >= rows) return;
    T* row = s + r * L;
    float m = NEG_INF;
    for (int j = lane; j < L; j += 32) m = fmaxf(m, ld(row + j));
    m = warp_max(m);
    float sum = 0.f;
    for (int j = lane; j < L; j += 32) sum += __expf(ld(row + j) - m);
    float inv = 1.f / warp_sum(sum);
    for (int j = lane; j < L; j += 32) st(row + j, __expf(ld(row + j) - m) * inv);
}

// Symmetric per-row int8 quantisation: q[r] = round(x[r] / s[r]), s[r] = max|x[r]| / 127.
// One warp per row; x rows are ldx apart, q rows are k apart.
template <typename T>
__device__ void quant_rows(const T* x, int ldx, signed char* q, float* s, int rows, int k) {
    int r = blockIdx.x * (blockDim.x / 32) + threadIdx.x / 32, lane = threadIdx.x % 32;
    if (r >= rows) return;
    const T* xr = x + (long)r * ldx;
    float m = 0.f;
    for (int c = lane; c < k; c += 32) m = fmaxf(m, fabsf(ld(xr + c)));
    m = warp_max(m);
    float sc = m > 0.f ? m / 127.f : 1.f, inv = 1.f / sc;
    for (int c = lane; c < k; c += 32) q[(long)r * k + c] = (signed char)__float2int_rn(ld(xr + c) * inv);
    if (lane == 0) s[r] = sc;
}

// out[r, c] (+)= acc[r, c] * sx[r] * sw[c] + bias[c], then ReLU if asked.
template <typename T>
__device__ void dequant(const int* acc, int n, const float* sx, const float* sw, const float* bias,
                        T* out, int ldo, long total, int accumulate, int relu) {
    long e = (long)blockIdx.x * blockDim.x + threadIdx.x;
    if (e >= total) return;
    long r = e / n;
    int c = e % n;
    float v = (float)acc[e] * sx[r] * sw[c] + bias[c];
    if (accumulate) v += ld(out + r * ldo + c);
    st(out + r * ldo + c, relu ? fmaxf(v, 0.f) : v);
}

#define BOTH(NAME, SIG, CALL)                                       \
    extern "C" __global__ void NAME##_f32 SIG { typedef float T; CALL; } \
    extern "C" __global__ void NAME##_f16 SIG { typedef half_t T; CALL; }

#define GATHER(TN, TT)                                                                         \
    BOTH(gather_##TN, (const int* codes, int nf, const int* fi, const int* off, int L, const void* tok, \
                       const float* ts, const void* qkv1, const float* qs, const void* ct, const float* cts, \
                       const void* cq, const float* cqs, int d, void* x, void* qkv, int with_qkv),       \
         (gather<TT, T>(codes, nf, fi, off, L, (const TT*)tok, ts, (const TT*)qkv1, qs, (const TT*)ct, cts, \
                        (const TT*)cq, cqs, d, (T*)x, (T*)qkv, with_qkv)))
GATHER(f32, float)
GATHER(f16, half_t)
GATHER(i8, signed char)
BOTH(attn_full_8, (const void* qkv, void* out, int L, int d), (attention_full<T, 8>((const T*)qkv, (T*)out, L, d)))
BOTH(attn_full_16, (const void* qkv, void* out, int L, int d), (attention_full<T, 16>((const T*)qkv, (T*)out, L, d)))
BOTH(attn_cls_8, (const void* q, const void* kv, void* out, int L, int d), (attention_cls<T, 8>((const T*)q, (const T*)kv, (T*)out, L, d)))
BOTH(attn_cls_16, (const void* q, const void* kv, void* out, int L, int d), (attention_cls<T, 16>((const T*)q, (const T*)kv, (T*)out, L, d)))
BOTH(layer_norm, (const void* x, int ld_in, void* y, const float* w, const float* b, int rows, int d, float eps),
     (layer_norm<T>((const T*)x, ld_in, (T*)y, w, b, rows, d, eps)))
BOTH(bias_act, (void* x, int ldx, const float* bias, int n, long total, int relu), (bias_act<T>((T*)x, ldx, bias, n, total, relu)))
BOTH(take_cls, (const void* x, void* c, int L, int d, long total), (take_cls<T>((const T*)x, (T*)c, L, d, total)))
BOTH(finish, (const void* y, int n, float* out, int dim, int col, float scale, int rows), (finish<T>((const T*)y, n, out, dim, col, scale, rows)))

BOTH(softmax_rows, (void* s, long rows, int L), (softmax_rows<T>((T*)s, rows, L)))
BOTH(quant_rows, (const void* x, int ldx, signed char* q, float* s, int rows, int k), (quant_rows<T>((const T*)x, ldx, q, s, rows, k)))
BOTH(dequant, (const int* acc, int n, const float* sx, const float* sw, const float* bias, void* out, int ldo, long total, int accumulate, int relu),
     (dequant<T>(acc, n, sx, sw, bias, (T*)out, ldo, total, accumulate, relu)))

// fp32 -> fp16 conversion for weight upload
extern "C" __global__ void to_half(const float* x, half_t* y, long n) {
    long e = (long)blockIdx.x * blockDim.x + threadIdx.x;
    if (e < n) st(y + e, x[e]);
}
