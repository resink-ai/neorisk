# Flink 2.2.1 with the Parquet format, the Kafka connector, and the shaded Hadoop client and
# zstd codec that the Parquet format needs (the logs are zstd-compressed). Every jar is pinned and fetched from Maven Central.
FROM flink:2.2.1-scala_2.12-java17

ARG MAVEN=https://repo1.maven.org/maven2
RUN cd /opt/flink/lib \
 && wget -q ${MAVEN}/org/apache/flink/flink-sql-parquet/2.2.1/flink-sql-parquet-2.2.1.jar \
 && wget -q ${MAVEN}/org/apache/flink/flink-sql-connector-kafka/5.0.0-2.2/flink-sql-connector-kafka-5.0.0-2.2.jar \
 && wget -q ${MAVEN}/org/apache/hadoop/hadoop-client-api/3.4.2/hadoop-client-api-3.4.2.jar \
 && wget -q ${MAVEN}/org/apache/hadoop/hadoop-client-runtime/3.4.2/hadoop-client-runtime-3.4.2.jar \
 && wget -q ${MAVEN}/com/github/luben/zstd-jni/1.5.7-3/zstd-jni-1.5.7-3.jar
