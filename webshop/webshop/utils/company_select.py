import frappe

def get_user_company(user=None):
    user = user or frappe.session.user

    if user == "Guest":
        return get_default_company()

    customer = frappe.db.get_value(
        "Portal User",
        {"user": user, "parenttype": "Customer"},
        "parent"
    )

    if not customer:
        return get_default_company()

    company = frappe.db.get_value(
        "Customer",
        customer,
        "custom_default_company"
    )

    return company or get_default_company()

def get_default_company():
    return frappe.db.get_single_value("Webshop Settings", "company")


def get_company_webshop_config(company=None):
    company = company or get_user_company()

    config = frappe.db.get_value(
        "Webshop Company Setting",
        {"company": company},
        [
            "company", "price_list", "payment_gateway_account",
            "quotation_series", "default_customer_group",
            "enable_checkout", "show_price","payment_success_url"
        ],
        as_dict=True
    )

    if not config:
        # Fallback to global Webshop Settings
        return frappe.get_single("Webshop Settings")

    return config