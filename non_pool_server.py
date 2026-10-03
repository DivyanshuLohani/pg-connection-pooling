import fastapi
import time
import psycopg2, uvicorn
from pydantic import BaseModel

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "pooling_demo",
    "user": "postgres",
    "password": "postgres",
}

class UserCreate(BaseModel):
    name: str
    email: str

app = fastapi.FastAPI()

@app.get("/users")
def get_users():
    start_time = time.perf_counter() 
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT * FROM users;")
        users = cur.fetchall()
        user_list = [{"id": user[0], "name": user[1], "email": user[2]} for user in users]
        return {"users": user_list, 'time': f"{1000 * (time.perf_counter() - start_time)} ms", }

    except Exception as e:
        return {"error": str(e)}

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
        print(f"Time non pooled: {time.perf_counter() - start_time}s")

@app.post("/users")
def create_user(user: UserCreate):
    start_time = time.perf_counter() 
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (name, email) VALUES (%s, %s) RETURNING id;", (user.name, user.email))
        user_id = cur.fetchone()[0]
        conn.commit()
        return {"id": user_id, "name": user.name, "email": user.email, 'time': f"{1000 * (time.perf_counter() - start_time)} ms"}

    except Exception as e:
        return {"error": str(e)}

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
        print(f"Time non pooled: {time.perf_counter() - start_time}s")

if __name__ == "__main__":
    uvicorn.run("non_pool_server:app", host="127.0.0.1", port=8000, reload=True)
