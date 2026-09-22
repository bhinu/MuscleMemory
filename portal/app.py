"""The chaos portal: a deliberately plain supplier ordering site.

Four pages: sign in, pick a product, fill in an order, see a confirmation.
Nothing is persisted and the login is not real security -- this site exists
to be driven by a browser agent and broken on purpose.
"""

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from portal import chaos, db

app = FastAPI()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

db.init_db()

PRODUCTS = {
    "SKU-1001": {"name": "Blue Widget", "price": "12.50"},
    "SKU-1002": {"name": "Red Widget", "price": "14.00"},
    "SKU-1003": {"name": "Steel Bracket", "price": "31.75"},
}


def logged_in(request: Request) -> bool:
    return "session" in request.cookies


def date_format(mutations: set[str]) -> tuple[str, str]:
    """The delivery date field's (strptime pattern, label shown to the user).

    Both come from one place so the form can never advertise a format the
    parser disagrees with.
    """
    if "date_format_dmy" in mutations:
        return "%d/%m/%Y", "DD/MM/YYYY"
    return "%m/%d/%Y", "MM/DD/YYYY"


@app.get("/")
def home(request: Request):
    return RedirectResponse("/products" if logged_in(request) else "/login", status_code=303)


@app.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
def login_submit(request: Request, username: str = Form(), password: str = Form()):
    response = RedirectResponse("/products", status_code=303)
    response.set_cookie("session", username)
    return response


@app.get("/products")
def product_list(request: Request):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "products.html", {"products": PRODUCTS})


@app.get("/order/{sku}")
def order_form(request: Request, sku: str):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    product = PRODUCTS.get(sku)
    if product is None:
        return RedirectResponse("/products", status_code=303)
    mutations = chaos.active()
    return templates.TemplateResponse(
        request,
        "order.html",
        {
            "sku": sku,
            "product": product,
            "mutations": mutations,
            "date_label": date_format(mutations)[1],
            "error": None,
        },
    )


@app.post("/order")
def order_submit(request: Request, sku: str = Form(), delivery_date: str = Form()):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    product = PRODUCTS.get(sku)
    if product is None:
        return RedirectResponse("/products", status_code=303)
    mutations = chaos.active()
    pattern, date_label = date_format(mutations)
    try:
        iso_date = datetime.strptime(delivery_date, pattern).date().isoformat()
    except ValueError:
        return templates.TemplateResponse(
            request,
            "order.html",
            {
                "sku": sku,
                "product": product,
                "mutations": mutations,
                "date_label": date_label,
                "error": f"Enter the delivery date as {date_label}.",
            },
        )
    number = db.save_order(sku, product["name"], iso_date)
    return templates.TemplateResponse(
        request,
        "confirmation.html",
        {
            "sku": sku,
            "product": product,
            "delivery_date": iso_date,
            "order_number": number,
        },
    )


@app.get("/orders")
def order_history(request: Request):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "orders.html", {"orders": db.list_orders()})
