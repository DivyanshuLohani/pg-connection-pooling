# PostgreSQL Connection Pooling Performance Demo


## Requirements

* Python 3.10+
* PostgreSQL
* Locust
* `psycopg2`
* FastAPI
* Uvicorn

---

## Setup

### 1. Create the PostgreSQL Database

Create the database:

```sql
CREATE DATABASE pooling_demo;
```

Connect to it:

```bash
psql -U postgres -d pooling_demo
```

Create the `users` table:

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(200) NOT NULL
);
```

Insert some test data:

```sql
INSERT INTO users (name, email)
SELECT
    'User ' || generate_series,
    'user' || generate_series || '@example.com'
FROM generate_series(1, 100);
```

```python
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "pooling_demo",
    "user": "postgres",
    "password": "postgres",
}
```

You can update password the db data in run_test.py and the server files

---

## 2. Create a Python Virtual Environment

```bash
python -m venv .venv
```


```bash
source .venv/bin/activate
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

# How the Demo Works

## No Pooling

The no-pooling server does this for every request:

```text
HTTP request
     |
     v
psycopg2.connect()
     |
     v
Execute SQL query
     |
     v
Close connection
     |
     v
HTTP response
```

We open a connection to the database on every request and then close after sending the response

---

## With Pooling

The pooling server creates a connection pool when the application starts.

For this experiment the pool is configured with a maximum of **10 connections**.

The request flow becomes:

```text
HTTP request
     |
     v
Borrow connection from pool
     |
     v
Execute SQL query
     |
     v
Return connection to pool
     |
     v
HTTP response
```

The connection itself is not closed after every request.

This allows subsequent requests to reuse existing PostgreSQL connections which reduces latency and extra steps

---

# Load Test

The load test uses **Locust**.

Both implementations receive exactly the same type of request:

```http
GET /users
```

The endpoint executes:

```sql
SELECT * FROM users;
```

The Locust configuration used for the experiment was:

```text
Concurrent users: 50
Spawn rate:       50 users/second
Test duration:    10 seconds
```

The same test was run against:

```text
non_pool_server.py
```

and:

```text
pooling_server.py
```

The test runner automatically starts and stops each server, so the servers do not need to be started manually.

---

# Running the Benchmark

Make sure PostgreSQL is running and the `pooling_demo` database exists.

Then simply run:

```bash
python run_test.py
```

The script will:

1. Start `non_pool_server.py`.
2. Wait for the server to become ready.
3. Start monitoring PostgreSQL connections using `pg_stat_activity`.
4. Run the Locust load test.
5. Record the results.
6. Stop the no-pooling server.
7. Start `pooling_server.py`.
8. Repeat exactly the same load test.
9. Stop the pooling server.
10. Print a final comparison table.

---

# Measuring PostgreSQL Connections

During each test, the benchmark periodically executes:

```sql
SELECT count(*)
FROM pg_stat_activity
WHERE datname = 'pooling_demo';
```

This provides an observation of the number of PostgreSQL sessions associated with the test database while the load test is running.

The connection monitor runs separately from the Locust requests so that every HTTP request does not introduce an additional monitoring query.

---

# Results

The following results were obtained from the experiment.

### Test configuration

| Setting           |                  Value |
| ----------------- | ---------------------: |
| Concurrent users  |                     50 |
| Test duration     |             10 seconds |
| Endpoint          |           `GET /users` |
| SQL query         | `SELECT * FROM users;` |
| Pool maximum size |                     10 |
| Failed requests   |                      0 |

### Measured results

| Metric                                  |    No Pool |  With Pool |
| --------------------------------------- | ---------: | ---------: |
| Concurrent users                        |         50 |         50 |
| Total requests                          |        269 |        277 |
| Failed requests                         |          0 |          0 |
| Average response time                   | 1453.35 ms | 1428.37 ms |
| Minimum response time                   |  299.97 ms |  138.02 ms |
| Maximum response time                   | 2638.44 ms | 2099.65 ms |
| Total test time                         |   10.657 s |   10.530 s |
| Maximum PostgreSQL connections observed |         34 |         17 |
| Average PostgreSQL connections observed |       2.80 |       5.49 |

### Average response-time difference

The measured average response time was:

```text
No Pool:    1453.35 ms
With Pool:  1428.37 ms
```

The pooling version was approximately:

```text
1.72%
```

lower in average response time in this particular run.

Also we can see that maximum connections to the database were significantly low when we are using the pooling method which helps reduce a lot of overhead on the database
and the average connections are also low because of the 

---

# Important Observation

The results demonstrate an important point about connection pooling:

> **Connection pooling is not guaranteed to make every individual query dramatically faster.**

In this experiment the SQL query itself is very simple:

```sql
SELECT * FROM users;
```

The database is also running locally, so PostgreSQL connection establishment may not be expensive enough to dominate the total request time.

As a result, the latency improvement was relatively small:

```text
1.72%
```

However, pooling still significantly changed how database connections were used:

```text
Maximum connections

No Pool:    34
With Pool:  17
```

This becomes increasingly important as application concurrency increases because opening a new PostgreSQL session for every request does not scale as well as reusing a bounded number of connections.

## Reproducing the Results

Run:

```bash
python run_test.py
```

The script will automatically produce a table similar to:

```text
====================================================================================================
FINAL RESULTS
====================================================================================================

Metric                                               No Pool           With Pool
--------------------------------------------------------------------------------
Concurrent users                                          50                  50
Total requests                                           269                 277
Failed requests                                            0                   0
Average response time (ms)                           1453.35             1428.37
Minimum response time (ms)                            299.97              138.02
Maximum response time (ms)                           2638.44             2099.65
Total test time (seconds)                             10.657              10.530
Max PostgreSQL connections                                34                  17
Average PostgreSQL connections                          2.80                5.49
--------------------------------------------------------------------------------
Average response improvement                           1.72%
====================================================================================================
```

The exact numbers will vary between runs because the benchmark depends on the machine, PostgreSQL configuration, operating-system scheduling, and current system load.