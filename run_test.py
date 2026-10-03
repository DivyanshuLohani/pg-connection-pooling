import csv
import os
import subprocess
import sys
import threading
import time

import psycopg2
import requests


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "pooling_demo",
    "user": "postgres",
    "password": "postgres",
}

HOST = "127.0.0.1"
PORT = 8000

CONCURRENT_USERS = 50
SPAWN_RATE = 50

# Each Locust user performs requests continuously for this period.
TEST_DURATION = "10s"

MONITOR_INTERVAL = 0.05


# =========================================================
# PostgreSQL connection monitor
# =========================================================

class ConnectionMonitor:

    def __init__(self):
        self.running = False
        self.samples = []
        self.thread = None

    def get_count(self):

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

        except Exception:
            return None

        finally:
            if cur:
                cur.close()

            if conn:
                conn.close()

    def monitor(self):

        while self.running:

            count = self.get_count()

            if count is not None:
                self.samples.append(count)

            time.sleep(MONITOR_INTERVAL)

    def start(self):

        self.samples = []
        self.running = True

        self.thread = threading.Thread(
            target=self.monitor,
            daemon=True,
        )

        self.thread.start()

    def stop(self):

        self.running = False

        if self.thread:
            self.thread.join(timeout=2)

    @property
    def max_connections(self):

        if not self.samples:
            return 0

        return max(self.samples)

    @property
    def average_connections(self):

        if not self.samples:
            return 0

        return sum(self.samples) / len(self.samples)


# =========================================================
# Server management
# =========================================================

def start_server(filename):

    print(f"\nStarting {filename}...")

    process = subprocess.Popen(
        [
            sys.executable,
            filename,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def output_reader():

        for line in process.stdout:
            print(f"[SERVER] {line}", end="")

    threading.Thread(
        target=output_reader,
        daemon=True,
    ).start()

    wait_for_server()

    return process


def wait_for_server():

    url = f"http://{HOST}:{PORT}/users"

    deadline = time.time() + 15

    while time.time() < deadline:

        try:

            requests.get(
                url,
                timeout=1,
            )

            print("Server is ready.")

            time.sleep(1)

            return

        except requests.RequestException:

            time.sleep(0.2)

    raise RuntimeError(
        "FastAPI server did not start."
    )


def stop_server(process):

    print("Stopping server...")

    if process.poll() is not None:
        return

    process.terminate()

    try:
        process.wait(timeout=5)

    except subprocess.TimeoutExpired:

        process.kill()
        process.wait()


# =========================================================
# Locust
# =========================================================

def run_locust(test_name):

    csv_prefix = f"results_{test_name}"

    command = [
        "locust",

        "-f",
        "tester.py",

        "--headless",

        "--host",
        f"http://{HOST}:{PORT}",

        "-u",
        str(CONCURRENT_USERS),

        "-r",
        str(SPAWN_RATE),

        "-t",
        TEST_DURATION,

        "--csv",
        csv_prefix,

        "--csv-full-history",

        "--only-summary",
    ]

    print()
    print("Running Locust:")
    print(" ".join(command))
    print()

    start = time.perf_counter()

    result = subprocess.run(
        command,
        text=True,
    )

    total_time = time.perf_counter() - start

    if result.returncode != 0:
        raise RuntimeError(
            "Locust failed."
        )

    return total_time, csv_prefix


# =========================================================
# Read Locust results
# =========================================================

def read_locust_results(csv_prefix):

    filename = f"{csv_prefix}_stats.csv"

    with open(filename, newline="") as file:

        rows = list(
            csv.DictReader(file)
        )

    # Find aggregated row.
    aggregated = None

    for row in rows:

        if row["Name"] == "Aggregated":

            aggregated = row
            break

    if aggregated is None:

        raise RuntimeError(
            f"Could not find Aggregated row in {filename}"
        )

    return {
        "requests": int(
            aggregated["Request Count"]
        ),

        "failures": int(
            aggregated["Failure Count"]
        ),

        "average_ms": float(
            aggregated["Average Response Time"]
        ),

        "min_ms": float(
            aggregated["Min Response Time"]
        ),

        "max_ms": float(
            aggregated["Max Response Time"]
        ),
    }


# =========================================================
# One experiment
# =========================================================

def run_experiment(name, server_file):

    print()
    print("=" * 70)
    print(f"RUNNING: {name}")
    print("=" * 70)

    server = None
    monitor = ConnectionMonitor()

    try:

        server = start_server(server_file)

        # Start connection monitoring immediately before
        # the load test.
        monitor.start()

        start = time.perf_counter()

        _, csv_prefix = run_locust(
            name.lower().replace(" ", "_")
        )

        total_time = time.perf_counter() - start

    finally:

        monitor.stop()

        if server:
            stop_server(server)

    locust_results = read_locust_results(
        csv_prefix
    )

    return {
        "name": name,
        "requests": locust_results["requests"],
        "failures": locust_results["failures"],
        "average_ms": locust_results["average_ms"],
        "min_ms": locust_results["min_ms"],
        "max_ms": locust_results["max_ms"],
        "total_time": total_time,
        "max_connections": monitor.max_connections,
        "average_connections": monitor.average_connections,
    }


# =========================================================
# Main
# =========================================================

def main():

    print()
    print("=" * 80)
    print("POSTGRESQL CONNECTION POOLING PERFORMANCE TEST")
    print("=" * 80)

    print()
    print(f"Concurrent users : {CONCURRENT_USERS}")
    print(f"Test duration    : {TEST_DURATION}")
    print()

    results = []

    # -----------------------------------------------------
    # No pooling
    # -----------------------------------------------------

    results.append(
        run_experiment(
            "No Pool",
            "non_pool_server.py",
        )
    )

    # Let PostgreSQL settle before the next experiment.
    time.sleep(3)

    # -----------------------------------------------------
    # Pooling
    # -----------------------------------------------------

    results.append(
        run_experiment(
            "With Pool",
            "pooling_server.py",
        )
    )

    # -----------------------------------------------------
    # Final table
    # -----------------------------------------------------

    no_pool = results[0]
    pool = results[1]

    print()
    print()
    print("=" * 100)
    print("FINAL RESULTS")
    print("=" * 100)

    print()

    print(
        f"{'Metric':<40}"
        f"{'No Pool':>20}"
        f"{'With Pool':>20}"
    )

    print("-" * 80)

    print(
        f"{'Concurrent users':<40}"
        f"{CONCURRENT_USERS:>20}"
        f"{CONCURRENT_USERS:>20}"
    )

    print(
        f"{'Total requests':<40}"
        f"{no_pool['requests']:>20}"
        f"{pool['requests']:>20}"
    )

    print(
        f"{'Failed requests':<40}"
        f"{no_pool['failures']:>20}"
        f"{pool['failures']:>20}"
    )

    print(
        f"{'Average response time (ms)':<40}"
        f"{no_pool['average_ms']:>20.2f}"
        f"{pool['average_ms']:>20.2f}"
    )

    print(
        f"{'Minimum response time (ms)':<40}"
        f"{no_pool['min_ms']:>20.2f}"
        f"{pool['min_ms']:>20.2f}"
    )

    print(
        f"{'Maximum response time (ms)':<40}"
        f"{no_pool['max_ms']:>20.2f}"
        f"{pool['max_ms']:>20.2f}"
    )

    print(
        f"{'Total test time (seconds)':<40}"
        f"{no_pool['total_time']:>20.3f}"
        f"{pool['total_time']:>20.3f}"
    )

    print(
        f"{'Max PostgreSQL connections':<40}"
        f"{no_pool['max_connections']:>20}"
        f"{pool['max_connections']:>20}"
    )

    print(
        f"{'Average PostgreSQL connections':<40}"
        f"{no_pool['average_connections']:>20.2f}"
        f"{pool['average_connections']:>20.2f}"
    )

    print("-" * 80)

    improvement = (
        (
            no_pool["average_ms"]
            - pool["average_ms"]
        )
        / no_pool["average_ms"]
        * 100
    )

    print(
        f"{'Average response improvement':<40}"
        f"{'':>20}"
        f"{improvement:>19.2f}%"
    )

    print("=" * 100)
    print()


if __name__ == "__main__":
    main()
