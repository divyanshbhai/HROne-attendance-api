"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pymongo import MongoClient
import calendar

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

try:
    client.admin.command("ping")
    print("Connected successfully")
except Exception as e:
    raise Exception(
        "The following error occurred: ", e)


IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(hour=h, minute=m, second=0, microsecond=0)
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    punch_out = punch_out.replace(tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

class PunchOut(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

class LogUpdateBody(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)
# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    q = {}
    if department:
        q["department"] = department
    skip = (page-1) * page_size
    total = db.employees.count_documents({})
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")
    ts = datetime.fromtimestamp(body.punched_at / 1000) if body.punched_at else datetime.now()
    d = ts.date().isoformat()
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    docs = list(db.attendance_logs.find(q))
    docs.sort(key=lambda d: d["date"], reverse=True)
    total = len(docs)
    page_docs = docs[(page - 1) * page_size : page * page_size]
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out                     [DONE]
#   PATCH /attendance/{emp_code}/{date}             [Temporarily done, needs review]
#   GET   /analytics/employees/{emp_code}/monthly   [DONE]
#   GET   /analytics/departments/summary            [DONE]
#   GET   /analytics/leaderboard/late               [DONE]
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #


@app.post("/attendance/punch-out")
def punch_out(body: PunchOut):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(404, "employee not found")

    ts = datetime.fromtimestamp(body.punched_at / 1000) if body.punched_at else datetime.now()
    d = ts.date().isoformat()

    lastLog = db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}, {"_id":0})

    if lastLog is None:
        raise HTTPException(404, "no punch-in record found for this date")
    if lastLog["punch_out"] is not None:
        raise HTTPException(409, "already punched out for this date")

    lastLog["punch_out"] = ts
    lastLog["work_hours"] = compute_work_hours(lastLog["punch_in"], ts)
    lastLog["overtime_minutes"] = compute_overtime(ts, emp["shift_end"], d)

    if lastLog["work_hours"] < 4.50:
        lastLog["half_day"] = True

    res = db.attendance_logs.update_one(
        {"emp_code": body.emp_code, "date": d},
        {"$set": {
            "punch_out": lastLog["punch_out"],
            "work_hours": lastLog["work_hours"],
            "overtime_minutes": lastLog["overtime_minutes"],
            "half_day": lastLog["half_day"]
        }}
    )       
    return lastLog



@app.patch("/attendance/{emp_code}/{date}")
def update_attendance(emp_code: str, date: str, body: LogUpdateBody):
    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")
        
    Log = db.attendance_logs.find_one({"emp_code": emp_code, "date": date}, {"_id":0})
    if Log is None:
        raise HTTPException(404, "no record found")
        
    history_entry = {
        "at": datetime.now(),
        "by": body.regularized_by,
        "reason": body.reason
    }

    if body.status:
        if body.status == "ABSENT" or body.status == "LEAVE":
            if body.punch_in or body.punch_out:
                raise HTTPException(422, "punch_in and punch_out should be null for ABSENT or LEAVE status")

            history_entry["changes"] = {
                "status": {
                    "from": Log["status"],
                    "to": body.status
                },
            }
            Log["status"] = body.status
            Log["punch_in"] = None
            Log["punch_out"] = None
            Log["work_hours"] = None
            Log["late_minutes"] = 0
            Log["overtime_minutes"] = 0
            Log["half_day"] = False
            Log["history"].append(history_entry)


        elif body.status == "PRESENT" or body.status == "WFH" or body.status == "ON_DUTY":
            if body.punch_in is None and Log["punch_in"] is None:
                raise HTTPException(422, "punch_in is required for PRESENT, WFH or ON_DUTY status")
            punch_in_time = datetime.fromtimestamp(body.punch_in / 1000) if body.punch_in else Log["punch_in"]
            punch_out_time = datetime.fromtimestamp(body.punch_out / 1000) if body.punch_out else Log["punch_out"]
            if punch_in_time and punch_out_time:
                if punch_out_time <= punch_in_time:
                    raise HTTPException(
                        status_code=422,
                        detail="punch_out must be after punch_in"
                    )

                if punch_out_time - punch_in_time > timedelta(hours=24):
                    raise HTTPException(
                        status_code=422,
                        detail="punch_out must be within 24 hours of punch_in"
                    )
            work_hours = compute_work_hours(punch_in_time, punch_out_time) if punch_out_time else None
            late_minutes = compute_late_minutes(punch_in_time, emp["shift_start"]) if punch_in_time else 0
            overtime_minutes = compute_overtime(punch_out_time, emp["shift_end"], date) if punch_out_time else 0
            half_day = True if work_hours and work_hours < 4.50 else False 

            history_entry["changes"] = {
                "status": {
                    "from": Log["status"],
                    "to": body.status
                },
                "punch_in": {
                    "from": Log["punch_in"],
                    "to": punch_in_time
                },
                "punch_out": {
                    "from": Log["punch_out"],
                    "to": punch_out_time
                },
                "work_hours": {
                    "from": Log["work_hours"],
                    "to": work_hours
                },
                "late_minutes": {
                    "from": Log["late_minutes"],
                    "to": late_minutes
                },
                "overtime_minutes": {
                    "from": Log["overtime_minutes"],
                    "to": overtime_minutes
                }
            }
            Log["status"] = body.status
            Log["punch_in"] = punch_in_time
            Log["punch_out"] = punch_out_time
            Log["work_hours"] = work_hours
            Log["late_minutes"] = late_minutes
            Log["overtime_minutes"] = overtime_minutes
            Log["half_day"] = half_day
            Log["history"].append(history_entry)

    elif body.punch_in and body.punch_out:
        punch_in_time = datetime.fromtimestamp(body.punch_in / 1000)
        punch_out_time = datetime.fromtimestamp(body.punch_out / 1000)
        if punch_out_time <= punch_in_time:
            raise HTTPException(
                status_code=422,
                detail="punch_out must be after punch_in"
            )
        if punch_out_time - punch_in_time > timedelta(hours=24):
            raise HTTPException(
                status_code=422,
                detail="punch_out must be within 24 hours of punch_in"
            )
        work_hours = compute_work_hours(punch_in_time, punch_out_time)
        late_minutes = compute_late_minutes(punch_in_time, emp["shift_start"])
        overtime_minutes = compute_overtime(punch_out_time, emp["shift_end"], date)
        half_day = True if work_hours < 4.50 else False
        history_entry = {
            "timestamp": datetime.now(),
            "changes": {
                "punch_in": {
                    "from": Log["punch_in"],
                    "to": punch_in_time
                },
                "punch_out": {
                    "from": Log["punch_out"],
                    "to": punch_out_time
                },
                "work_hours": {
                    "from": Log["work_hours"],
                    "to": work_hours
                },
                "late_minutes": {
                    "from": Log["late_minutes"],
                    "to": late_minutes
                },
                "overtime_minutes": {
                    "from": Log["overtime_minutes"],
                    "to": overtime_minutes
                }
            }
        }
        Log["punch_in"] = punch_in_time
        Log["punch_out"] = punch_out_time
        Log["work_hours"] = work_hours
        Log["late_minutes"] = late_minutes
        Log["overtime_minutes"] = overtime_minutes
        Log["half_day"] = half_day
        Log["history"].append(history_entry)
    
    elif body.punch_in:
        punch_in_time = datetime.fromtimestamp(body.punch_in / 1000)
        punch_out_time = Log["punch_out"]
        if Log["punch_out"] is not None and punch_in_time >= punch_out_time:
            raise HTTPException(
                status_code=422,
                detail="punch_in must be before punch_out"
            )
        if Log["punch_out"] is not None and punch_in_time < punch_out_time and punch_out_time - punch_in_time > timedelta(hours=24):
            raise HTTPException(
                status_code=422,
                detail="punch_in must be within 24 hours of punch_out"
            )
            
        history_entry = {
            "timestamp": datetime.now(),
            "changes": {
                "punch_in": {
                    "from": Log["punch_in"],
                    "to": punch_in_time
                }
            }
        }    
        Log["punch_in"] = punch_in_time
        Log["late_minutes"] = compute_late_minutes(punch_in_time, emp["shift_start"])
        if punch_out_time:
            Log["work_hours"] = compute_work_hours(punch_in_time, punch_out_time)
            Log["overtime_minutes"] = compute_overtime(punch_out_time, emp["shift_end"], date)
            Log["half_day"] = True if Log["work_hours"] < 4.50 else False
        Log["history"].append(history_entry)
    
    elif body.punch_out:
        punch_out_time = datetime.fromtimestamp(body.punch_out / 1000)
        punch_in_time = Log["punch_in"]
        if punch_out_time and punch_out_time <= punch_in_time:
            raise HTTPException(
                status_code=422,
                detail="punch_in must be before punch_out"
            )
        if punch_out_time and punch_out_time - punch_in_time > timedelta(hours=24):
            raise HTTPException(
                status_code=422,
                detail="punch_in must be within 24 hours of punch_out"
            )
        history_entry = {
            "timestamp": datetime.now(),
            "changes": {
                "punch_out": {
                    "from": Log["punch_out"],
                    "to": punch_out_time
                }
            }
        }
        Log["punch_out"] = punch_out_time
        if Log["punch_in"]:
            Log["work_hours"] = compute_work_hours(Log["punch_in"], punch_out_time)
            Log["overtime_minutes"] = compute_overtime(punch_out_time, emp["shift_end"], date)
            Log["half_day"] = True if Log["work_hours"] < 4.50 else False
        Log["history"].append(history_entry)

    
    res = db.attendance_logs.update_one(
        {"emp_code": emp_code, "date": date},
        {"$set": {
            "status": Log["status"],
            "punch_in": Log["punch_in"],
            "punch_out": Log["punch_out"],
            "work_hours": Log["work_hours"],
            "late_minutes": Log["late_minutes"],
            "overtime_minutes": Log["overtime_minutes"],
            "half_day": Log["half_day"],
            "history": Log["history"]
        }}
    )   

    return Log



@app.get("/analytics/employees/{emp_code}/monthly")
def monthly_analytics(emp_code: str, month: str):
    
    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")
    
    if month is None or len(month) != 7 or month[4] != '-' or not month[:4].isdigit() or not month[5:].isdigit():
        raise HTTPException(422, "month must be in YYYY-MM format")

    m_y = month.split('-')
    if not 1900 <= int(m_y[0]) <= 9999 or not 1 <= int(m_y[1]) <= 12:
        raise HTTPException(422, "invalid month")


    doc = db.attendance_logs.aggregate([
        {"$match": {
            "emp_code": emp_code,
            "date": {"$regex": f"^{month}-"}
        }},  {"$project": {"_id": 0}}  
    ])
    year = int(m_y[0])
    month_num = int(m_y[1])

    total_days = calendar.monthrange(year, month_num)[1]
    working_days = 0

    for i in range(1, total_days + 1):
        day = datetime(year, month_num, i)

        if day.weekday() < 5:
            working_days += 1
    present_days = 0
    leave_days = 0
    late_count = 0
    total_late_minutes = 0
    total_overtime_minutes = 0

    for d in doc:
        if d["status"] in ["PRESENT", "WFH", "ON_DUTY"]:
            if d["work_hours"] < 4.5:
                present_days += 0.5
            else:
                present_days += 1
            if d["late_minutes"] > 0:
                late_count += 1
                total_late_minutes += d["late_minutes"]

        elif d["status"] == "LEAVE":
            leave_days += 1

        total_overtime_minutes += d["overtime_minutes"]

    result = {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": leave_days,
        "late_count": late_count,
        "total_late_minutes": total_late_minutes,
        "total_overtime_minutes": total_overtime_minutes
    }

    return result



@app.get("/analytics/departments/summary")
def department_summary(month: str, department: Optional[str] = None):
    if month is None or len(month) != 7 or month[4] != '-' or not month[:4].isdigit() or not month[5:].isdigit():
        raise HTTPException(422, "month must be in YYYY-MM format")

    m_y = month.split('-')
    if not 1900 <= int(m_y[0]) <= 9999 or not 1 <= int(m_y[1]) <= 12:
        raise HTTPException(422, "invalid month")
    
    response = db.employees.aggregate([
        {"$match": {
                "joined_on": {"$lte": f"{month}-31"},
                **({"department": department} if department else {})
            }},
        {"$group": {
            "_id": "$department",
            "headcount": {"$sum": 1}
        }},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"dept": "$_id"},
            "pipeline": [
                {"$match": {
                    "$expr": {
                        "$and": [
                            {"$eq": ["$department", "$$dept"]},
                            {"$regexMatch": {"input": "$date", "regex": f"^{month}-"}}
                        ]
                    }
                }},
                {"$group": {
                    "_id": "$emp_code",
                    "present_days": {"$sum": {"$cond": [    {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]}, {"$cond": [{"$lt": ["$work_hours", 4.5]}, 0.5, 1]}, 0]}},
                    "avg_work_hours": {"$avg": "$work_hours"},
                    "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}},
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "leave_count": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
                    "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]}}
                }},
                {"$group": {
                    "_id": None,
                    "present_days": {"$sum": "$present_days"},
                    "avg_work_hours": {"$avg": "$avg_work_hours"},
                    "late_count": {"$sum": "$late_count"},
                    "total_late_minutes": {"$sum": "$total_late_minutes"},
                    "leave_count": {"$sum": "$leave_count"},
                    "on_duty_count": {"$sum": "$on_duty_count"}
                }}
            ],
            "as": "attendance_summary"
        }},
        {"$unwind": {"path": "$attendance_summary", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "department": "$_id",
            "headcount": 1,
            "present_days": {"$ifNull": ["$attendance_summary.present_days", 0]},
            "avg_work_hours": {"$ifNull": ["$attendance_summary.avg_work_hours", None]},
            "late_count": {"$ifNull": ["$attendance_summary.late_count", 0]},
            "total_late_minutes": {"$ifNull": ["$attendance_summary.total_late_minutes", 0]},
            "leave_count": {"$ifNull": ["$attendance_summary.leave_count", 0]},
            "on_duty_count": {"$ifNull": ["$attendance_summary.on_duty_count", 0]}
        }},
        {"$sort": {"department": 1}}
    ])
    output = list(response)

    result = {
        "month": month,
        "items": [output]
    }

    return result

    


@app.get("/analytics/leaderboard/late")
def leaderboard_late(month: str, limit: int = 10, department: Optional[str] = None):
    if month is None or len(month) != 7 or month[4] != '-' or not month[:4].isdigit() or not month[5:].isdigit():
        raise HTTPException(422, "month must be in YYYY-MM format")

    m_y = month.split('-')
    if not 1900 <= int(m_y[0]) <= 9999 or not 1 <= int(m_y[1]) <= 12:
        raise HTTPException(422, "invalid month")

    if limit < 1 or limit > 50:
        raise HTTPException(422, "limit must be between 1 and 50")

    pipeline = [
        {"$match": {
            "date": {"$regex": f"^{month}-"},
            "late_minutes": {"$gt": 0}
        }},
        {"$group": {
            "_id": "$emp_code",
            "total_late_minutes": {"$sum": "$late_minutes"},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}}
        }},
        {"$lookup": {
            "from": "employees",
            "localField": "_id",
            "foreignField": "emp_code",
            "as": "employee"
        }},
        {"$unwind": "$employee"},
        {"$project": {
            "_id": 0,
            "emp_code": "$_id",
            "name": "$employee.name",
            "department": "$employee.department",
            "total_late_minutes": 1,
            "late_count": 1
        }},
        {"$sort": {
            "total_late_minutes": -1,
            "emp_code": 1
        }}
    ]

    if department:
        pipeline.insert(2, {"$match": {"employee.department": department}})

    leaderboard = list(db.attendance_logs.aggregate(pipeline))

    # ranking
    rank = 1
    prev_total_late_minutes = None
    for i, entry in enumerate(leaderboard):
        if prev_total_late_minutes is None or entry["total_late_minutes"] < prev_total_late_minutes:
            rank = i + 1
        entry["rank"] = rank
        prev_total_late_minutes = entry["total_late_minutes"]

    # Apply limit after ranking
    leaderboard = [entry for entry in leaderboard if entry["rank"] <= limit]
    return leaderboard





@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, date_from: str, date_to: str):
    # Validate date format
    try:
        start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
        end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, "Invalid date format. Use YYYY-MM-DD.")

    if end_date < start_date:
        raise HTTPException(422, "to < from")
    
    if (end_date - start_date).days > 92:
        raise HTTPException(422, "Range cannot exceed 92 days.")

    # Check if department has employees
    headcount = db.employees.count_documents({"department": department})
    if headcount == 0:
        raise HTTPException(404, "No employees found for this department.")

    items = []
    current_date = start_date
    while current_date <= end_date:
        is_working_day = current_date.weekday() < 5  # Monday=0, Sunday=6
        date_str = current_date.isoformat()

        # Get attendance logs for the current date
        logs = list(db.attendance_logs.find({"date": date_str, "emp_code": {"$in": [e["emp_code"] for e in db.employees.find({"department": department})]}}, {"_id": 0}))

        present_count = sum(0.5 if log["work_hours"] < 4.5 else 1 for log in logs if log["status"] in ["PRESENT", "WFH", "ON_DUTY"])
        late_count = sum(1 for log in logs if log["late_minutes"] > 0)

        attendance_rate = round(present_count / headcount, 4) if is_working_day and headcount > 0 else None

        items.append({
            "date": date_str,
            "is_working_day": is_working_day,
            "headcount": headcount,
            "present_count": present_count,
            "late_count": late_count,
            "attendance_rate": attendance_rate,
            "moving_avg_7d": None  # Placeholder for moving average calculation
        })

        current_date += timedelta(days=1)

    # Calculate moving average for attendance_rate
    for i in range(len(items)):
        rates = [item["attendance_rate"] for item in items[max(0, i-6):i+1] if item["attendance_rate"] is not None]
        if rates:
            items[i]["moving_avg_7d"] = round(sum(rates) / len(rates), 4)
    
    result = {
        "department": department,
        "items": items
    }
    return result


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: str, emp_code: Optional[str] = None, month: Optional[str] = None, department: Optional[str] = None, limit: Optional[int] = None, date_from: Optional[str] = None, date_to: Optional[str] = None, status: Optional[str] = None, page: Optional[int] = 1, page_size: Optional[int] = 20):
    if endpoint not in ["attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"]:
        raise HTTPException(422, "invalid endpoint")

    if endpoint == "attendance_list":
        if date_from is None or date_to is None:
            raise HTTPException(422, "date_from and date_to are required for attendance_list")
        q = {}
        if emp_code:
            q["emp_code"] = emp_code
        if date_from or date_to:
            q["date"] = {}
            if date_from:
                q["date"]["$gte"] = date_from
            if date_to:
                q["date"]["$lte"] = date_to
        if status:
            q["status"] = status
        explain = db.attendance_logs.find(q).skip((page-1)*page_size).limit(page_size).explain("executionStats")
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": explain}
    
