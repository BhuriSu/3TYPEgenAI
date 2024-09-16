
import sys
import warnings
import traceback
import logging

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s:%(funcName)s:%(levelname)s:%(message)s') # One can see the logs to understand possible errors better. Log levels were determined due to method importance.

warnings.filterwarnings('ignore')
checkpointDir = "file:///tmp/streaming/kafka_tourist_input" # Historical data is kept here. Can be deleted after each run for development purposes.

# Below creates the format for tourist_input index.
tourist_input_index = {
    "settings": {
        "index": {
            "analysis": {
                "analyzer": {
                    "custom_analyzer":
                        {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": [
                                "lowercase", "custom_edge_ngram", "asciifolding"
                            ]
                        }
                },
                "filter": {
                    "custom_edge_ngram": {
                        "type": "edge_ngram",
                        "min_gram": 2,
                        "max_gram": 10
                    }
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "date": {"type": "date",
            "format": "yyyy-MM-d hh:mm:ss||yyyy-MM-dd hh:mm:ss||yyyy-MM-dd HH:mm:ss||yyyy-MM-d HH:mm:ss",
            "ignore_malformed": "true"
      },
            "province_eng": {"type": "string"},
            "region_eng": {"type": "string"},
            "value": {"type": "float"}
        }
    }
}


def create_spark_session():
    """
    Creates the Spark Session with suitable configs.
    """
    from pyspark.sql import SparkSession
    try:
        # Spark session is established with elasticsearch and kafka jars. Suitable versions can be found in Maven repository.
        spark = (SparkSession.builder
                 .appName("Streaming Kafka-Spark")
                 .config("spark.jars.packages", "org.elasticsearch:elasticsearch-spark-30_2.12:7.12.0,org.apache.spark:spark-sql-kafka-0-10_2.12:3.0.0")
                 .config("spark.driver.memory", "2048m")
                 .config("spark.sql.shuffle.partitions", 4)
                 .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
                 .getOrCreate())
        logging.info('Spark session created successfully')
    except Exception:
        traceback.print_exc(file=sys.stderr) # To see traceback of the error.
        logging.error("Couldn't create the spark session")

    return spark


def create_initial_dataframe(spark_session):
    """
    Reads the streaming data and creates the initial dataframe accordingly.
    """
    try:
        # Gets the streaming data from topic tourist_input.
        df = spark_session \
          .readStream \
          .format("kafka") \
          .option("kafka.bootstrap.servers", "localhost:9092") \
          .option("subscribe", "tourist_input") \
          .load()
        logging.info("Initial dataframe created successfully")
    except Exception as e:
        logging.warning(f"Initial dataframe couldn't be created due to exception: {e}")
    return df


def create_final_dataframe(df, spark_session):
    """
    Modifies the initial dataframe, and creates the final dataframe.
    """
    from pyspark.sql.types import IntegerType, FloatType, StringType
    from pyspark.sql import functions as F
    df2 = df.selectExpr("CAST(value AS STRING)") 

    df3 = df2.withColumn("date", F.split(F.col("value"), ",")[0].cast(IntegerType())) \
        .withColumn("province_eng", F.split(F.col("value"), ",")[1].cast(StringType())) \
        .withColumn("region_eng", F.split(F.col("value"), ",")[2].cast(StringType())) \
        .withColumn("value", F.split(F.col("value"), ",")[3].cast(FloatType())) \
        .drop(F.col("value")) # Define data types of all columns.

    df3.createOrReplaceTempView("df3")

    df4 = spark_session.sql("""
    select
      date,
      province_eng,
      region_eng,
      value,
    from df3
   
    """)
    logging.info("Final dataframe created successfully")
    return df4


def create_elasticsearch_connection():
    """
    Creates the ES connection.
    """
    from elasticsearch import Elasticsearch
    try:
        es = Elasticsearch("http://localhost:9200")
        logging.info(f"Connection {es} created successfully") # Prints the connection details.
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        logging.error("Couldn't create the final dataframe")

    return es


def check_if_index_exists(es):
    """
    Checks if index tourist_input exists. If not, creates it and prints message accordingly.
    """
    if es.indices.exists(index="tourist_input"):
        print("Index tourist_input already exists")
        logging.info("Index tourist_input already exists")
    else:
        es.indices.create(index="tourist_input", body=tourist_input_index)
        print("Index tourist_input created")
        logging.info("Index tourist_input created")


def start_streaming(df, es):
    """
    Starts the streaming to index tourist_input in elasticsearch.
    """
    logging.info("Streaming is being started...")
    my_query = (df.writeStream
                   .format("org.elasticsearch.spark.sql")
                   .outputMode("append")
                   .option("es.nodes", "localhost")
                   .option("es.port", "9200")
                   .option("es.resource", "tourist_input/_doc")
                   .option("checkpointLocation", checkpointDir)
                   .start())

    return my_query.awaitTermination()


if __name__ == '__main__':
    spark = create_spark_session()
    df = create_initial_dataframe(spark)
    df_final = create_final_dataframe(df, spark)
    es = create_elasticsearch_connection()
    check_if_index_exists(es)
    start_streaming(df_final, es)