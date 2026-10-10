# REVIEW.md

List every defect you found in the starter `app/main.py` (helpers and endpoints). For each one:

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | /employees GET: inside list_employees function | Calculation of Skip is wrong | When I call the API, it skips the first page documents | Changed `page * page_size` to `(page - 1) * page_size` |
| 2 | /attendance/punch-in: inside punch_in function | Employee is not checked before accessing shift_start | When I use a wrong emp_code, it gives an error instead of proper response | Added employee check and return 404 if employee not found |
| 3 | MongoDB connection | Connection was not checked | If MongoDB is not running, connection problem may not be clear at startup | Added ping check to verify connection |
| 4 | compute_overtime function | Timezone mismatch can cause subtraction error | When punch_out has timezone and end time does not, it can give TypeError | Added IST timezone to punch_out, but needs further testing |
| 5 | /attendance/punch-out | This API was missing in starter code | When I call punch-out API, it returns 404 | Added punch-out API with work hours, overtime and half-day calculation |

Also note anything you looked at and decided was **not** a defect, and why.
