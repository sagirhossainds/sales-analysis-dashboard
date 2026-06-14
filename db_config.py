import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="sales_user",
        password="Sales@123",
        database="sales_db"
    )


