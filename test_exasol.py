
import pyexasol
import getpass

password = getpass.getpass("Enter Exasol SYS password: ")

conn = pyexasol.connect(
    dsn="127.0.0.1:8563",
    user="sys",
    password=password,
    websocket_sslopt={"cert_reqs": 0},
)

try:
    result = conn.execute("SELECT 1").fetchall()
    print("Connection successful!")
    print("Query result:", result)
finally:
    conn.close()
