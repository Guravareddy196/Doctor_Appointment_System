from contextlib import contextmanager

import mysql.connector

from config import Config


def get_connection(database=True):
    connection_config = {
        "host": Config.MYSQL_HOST,
        "port": Config.MYSQL_PORT,
        "user": Config.MYSQL_USER,
        "password": Config.MYSQL_PASSWORD,
    }
    if database:
        connection_config["database"] = Config.MYSQL_DB
    return mysql.connector.connect(**connection_config)


@contextmanager
def db_cursor(dictionary=True):
    connection = get_connection()
    cursor = connection.cursor(dictionary=dictionary)
    try:
        yield connection, cursor
    finally:
        cursor.close()
        connection.close()


def fetch_all(query, params=None):
    with db_cursor() as (_, cursor):
        cursor.execute(query, params or ())
        return cursor.fetchall()


def fetch_one(query, params=None):
    with db_cursor() as (_, cursor):
        cursor.execute(query, params or ())
        return cursor.fetchone()
