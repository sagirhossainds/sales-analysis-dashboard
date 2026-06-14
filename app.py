import pandas as pd
from flask import send_file
import io
from flask import Flask, render_template, request, redirect, session
from db_config import get_connection

app = Flask(__name__)
app.secret_key = "sales_rt_secret_123"  # ok for project

def login_required(fn):
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect("/login")
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT username, role FROM users WHERE username=%s AND password=%s",
            (username, password)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session["user"] = user["username"]
            session["role"] = user["role"]
            return redirect("/")
        return render_template("login.html", error="Invalid username or password")

    return render_template("login.html", error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
@login_required
def dashboard():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # KPI
    cur.execute("""
        SELECT
          COUNT(*) AS total_orders,
          ROUND(SUM(IFNULL(total_amount, 0)), 2) AS total_revenue,
          ROUND(AVG(IFNULL(total_amount, 0)), 2) AS avg_order
        FROM sales;
    """)
    kpi = cur.fetchone() or {"total_orders": 0, "total_revenue": 0, "avg_order": 0}

    # Product summary (bar chart + table)
    cur.execute("""
        SELECT p.product_name,
               SUM(s.quantity) AS total_quantity,
               ROUND(SUM(IFNULL(s.total_amount, s.quantity * p.price)), 2) AS total_sales
        FROM sales s
        JOIN products p ON s.product_id = p.product_id
        GROUP BY p.product_name
        ORDER BY total_sales DESC;
    """)
    product_data = cur.fetchall()

    # Monthly trend (line chart)
    cur.execute("""
        SELECT DATE_FORMAT(sale_date, '%Y-%m') AS month,
               ROUND(SUM(IFNULL(total_amount, 0)), 2) AS sales
        FROM sales
        GROUP BY month
        ORDER BY month;
    """)
    monthly_data = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        kpi=kpi,
        product_data=product_data,
        monthly_data=monthly_data
    )

@app.route("/add-sale", methods=["GET", "POST"])
@login_required
def add_sale():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Load dropdown data
    cur.execute("SELECT customer_id, customer_name, city FROM customers ORDER BY customer_name;")
    customers = cur.fetchall()

    cur.execute("SELECT product_id, product_name, price FROM products ORDER BY product_name;")
    products = cur.fetchall()

    if request.method == "POST":
        try:
            product_id = int(request.form["product_id"])
            customer_id = int(request.form["customer_id"])
            quantity = int(request.form["quantity"])
            sale_date = request.form["sale_date"]

            if quantity <= 0:
                raise ValueError("Quantity must be > 0")

            # Call stored procedure for real DB logic
            cur2 = conn.cursor()
            cur2.callproc("add_sale", (product_id, customer_id, quantity, sale_date))
            conn.commit()
            cur2.close()

            cur.close()
            conn.close()
            return render_template("add_sale.html", customers=customers, products=products, msg="Sale added successfully!", error=None)

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return render_template("add_sale.html", customers=customers, products=products, msg=None, error=str(e))

    cur.close()
    conn.close()
    return render_template("add_sale.html", customers=customers, products=products, msg=None, error=None)

@app.route("/export/sales/csv")
@login_required
def export_sales_csv():
    conn = get_connection()
    df = pd.read_sql("""
        SELECT s.sale_id, p.product_name, c.customer_name,
               s.quantity, s.sale_date, s.total_amount
        FROM sales s
        JOIN products p ON s.product_id = p.product_id
        JOIN customers c ON s.customer_id = c.customer_id
    """, conn)
    conn.close()

    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="sales_data.csv"
    )
@app.route("/export/sales/excel")
@login_required
def export_sales_excel():
    conn = get_connection()
    df = pd.read_sql("""
        SELECT s.sale_id, p.product_name, c.customer_name,
               s.quantity, s.sale_date, s.total_amount
        FROM sales s
        JOIN products p ON s.product_id = p.product_id
        JOIN customers c ON s.customer_id = c.customer_id
    """, conn)
    conn.close()

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="sales_data.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
@app.route("/import/sales", methods=["GET", "POST"])
@login_required
def import_sales():
    if request.method == "POST":
        try:
            file = request.files["file"]
            df = pd.read_csv(file)

            conn = get_connection()
            cur = conn.cursor()

            for _, row in df.iterrows():
                cur.callproc(
                    "add_sale",
                    (
                        int(row["product_id"]),
                        int(row["customer_id"]),
                        int(row["quantity"]),
                        row["sale_date"]
                    )
                )

            conn.commit()
            cur.close()
            conn.close()

            return render_template("import.html", msg="Sales data imported successfully!", error=None)

        except Exception as e:
            return render_template("import.html", msg=None, error=str(e))

    return render_template("import.html", msg=None, error=None)
if __name__ == "__main__":
    app.run(debug=True)
