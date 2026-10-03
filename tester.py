import os
import subprocess
import time

import psycopg2
from locust import HttpUser, between, task, events


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "pooling_demo",
    "user": "postgres",
    "password": "postgres",
}

SERVER_TYPE = os.getenv("SERVER_TYPE", "non_pool")

SERVER_FILES = {
    "non_pool": "non_pool_server.py",
    "pool": "pooling_server.py",
}

server_process = None

connection_samples = []


def get_postgres_connection_count():
    """
    Get the number of PostgreSQL connections currently visible
    for the pooling_demo database.
    """

    conn = None
    cur = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = %s;
            """,
            (DB_CONFIG["database"],),
        )

        return cur.fetchone()[0]

    except Exception as e:
        print(f"Could not read pg_stat_activity: {e}")
        return None

    finally:
        if cur is not None:
            cur.close()

        if conn is not None:
            conn.close()


def start_server():
    global server_process

    server_file = SERVER_FILES[SERVER_TYPE]

    print(f"\nStarting {server_file}...\n")

    server_process = subprocess.Popen(
        ["python", server_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Artificial Delay
    deadline = time.time() + 15

    while time.time() < deadline:

        if server_process.poll() is not None:
            raise RuntimeError(
                f"{server_file} exited before starting."
            )

        try:
            import urllib.request

            urllib.request.urlopen(
                "http://127.0.0.1:8000/users",
                timeout=1,
            )

            print("Server is ready.")
            return

        except Exception:
            time.sleep(0.2)

    raise RuntimeError("Server did not start within 15 seconds.")


def stop_server():
    global server_process

    if server_process is None:
        return

    print("\nStopping server...")

    server_process.terminate()

    try:
        server_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_process.kill()

    server_process = None


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    start_server()


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stop_server()

    if connection_samples:
        print("\nPostgreSQL connection measurements:")

        print(
            f"Minimum: {min(connection_samples)}"
        )

        print(
            f"Maximum: {max(connection_samples)}"
        )

        print(
            f"Average: "
            f"{sum(connection_samples) / len(connection_samples):.2f}"
        )


class PostgreSQLUser(HttpUser):
    host = "http://127.0.0.1:8000"
    wait_time = between(0.01, 0.05)

    @task
    def get_users(self):
        response = self.client.get(
            "/users",
            name="GET /users",
        )

        # Take a connection sample after each request.
        count = get_postgres_connection_count()

        if count is not None:
            connection_samples.append(count)

        if response.status_code != 200:
            response.failure(
                f"HTTP {response.status_code}"
            )
