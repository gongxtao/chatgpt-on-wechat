from minio import Minio
from minio.error import S3Error

from config import conf, load_config

client = Minio(conf().get("minio_url"), conf().get("minio_access_key"), conf().get("minio_secret_key"), secure=False)
bucket_name = conf().get("minio_bucket_name")

def put_object(object_name, source_file):
    client.fput_object(conf().get("minio_bucket_name"), object_name, source_file)

def get_object(object_name) -> bytes:
    response = client.get_object(bucket_name, object_name)
    if response.status != 200:
        raise "failed to download the object: {}".format(object_name)
    return response.data


