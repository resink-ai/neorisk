"""Search for the computation behind local007 gold answers (a: 4.85, b: 5.09966563). Usage: python3 -I g2_local007_search.py DB"""
import sqlite3, sys, datetime as dt
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = con.execute("select debut, final_game from player").fetchall()
def r2(x): return round(x + 0.0, 2)
def variants():
    out = {}
    def agg(name, f, filt=lambda a,b: a!='' and b!=''):
        v=[f(a,b) for a,b in rows if filt(a,b)]; out[name]=(sum(v)/len(v), len(v))
    p=lambda s:(int(s[:4]),int(s[5:7]),int(s[8:10]))
    agg("fieldwise y,m,d diffs", lambda a,b: r2(abs(p(b)[0]-p(a)[0]))+r2(abs(p(b)[1]-p(a)[1])/12)+r2(abs(p(b)[2]-p(a)[2])/365))
    agg("fieldwise, int division (m/12, d/365 -> 0)", lambda a,b: abs(p(b)[0]-p(a)[0]) + abs(p(b)[1]-p(a)[1])//12 + abs(p(b)[2]-p(a)[2])//365)
    def dd(a,b): return (dt.date(*p(b))-dt.date(*p(a))).days
    agg("total days split y=D//365, m=(D%365)//30, d=(D%365)%30", lambda a,b: r2(dd(a,b)//365)+r2(((dd(a,b)%365)//30)/12)+r2(((dd(a,b)%365)%30)/365))
    agg("D/365.25", lambda a,b: dd(a,b)/365.25); agg("D/365", lambda a,b: dd(a,b)/365)
    agg("years = D/365 (real), months = D/30 /12 , days = D /365", lambda a,b: r2(dd(a,b)/365)+r2(dd(a,b)/30/12)+r2(dd(a,b)/365))
    agg("y diff + m diff/12 + d diff/365 (signed)", lambda a,b: r2(p(b)[0]-p(a)[0])+r2((p(b)[1]-p(a)[1])/12)+r2((p(b)[2]-p(a)[2])/365))
    agg("abs of signed sum", lambda a,b: abs(r2(p(b)[0]-p(a)[0])+r2((p(b)[1]-p(a)[1])/12)+r2((p(b)[2]-p(a)[2])/365)))
    # with '' treated as 0 dates (SQLite substr/cast of '' -> 0)
    p0=lambda s:(int(s[:4]),int(s[5:7]),int(s[8:10])) if s else (0,0,0)
    agg("fieldwise, all rows, '' -> 0", lambda a,b: r2(abs(p0(b)[0]-p0(a)[0]))+r2(abs(p0(b)[1]-p0(a)[1])/12)+r2(abs(p0(b)[2]-p0(a)[2])/365), lambda a,b: True)
    # months as total-month difference
    agg("y diff + total months diff/12 + d/365", lambda a,b: r2(abs(p(b)[0]-p(a)[0]))+r2(abs((p(b)[0]-p(a)[0])*12+p(b)[1]-p(a)[1])/12)+r2(abs(p(b)[2]-p(a)[2])/365))
    def ymd(a,b):
        A,B=p(a),p(b); y=B[0]-A[0]; m=B[1]-A[1]; d=B[2]-A[2]
        if d<0: m-=1; d+=30
        if m<0: y-=1; m+=12
        return y,m,d
    agg("borrowed y,m,d (30-day months)", lambda a,b: r2(abs(ymd(a,b)[0]))+r2(abs(ymd(a,b)[1])/12)+r2(abs(ymd(a,b)[2])/365))
    return out
for k,(v,n) in variants().items(): print(f"{v:.8f}  n={n}  {k}")
