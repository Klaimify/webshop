# import frappe
# from frappe.utils import get_url

# from erpnext.accounts.doctype.payment_request.payment_request import (
#     PaymentRequest as OriginalPaymentRequest,
# )


# class PaymentRequest(OriginalPaymentRequest):
#     def on_payment_authorized(self, status=None):
#         if not status:
#             return

#         if status not in ("Authorized", "Completed"):
#             return

#         if not hasattr(frappe.local, "session"):
#             return

#         if frappe.local.session.user == "Guest":
#             return

#         cart_settings = frappe.get_doc("Webshop Settings")

#         if not cart_settings.enabled:
#             return

#         success_url = cart_settings.payment_success_url
#         redirect_to = get_url("/orders/{0}".format(self.reference_name))

#         if success_url:
#             redirect_to = (
#                 {
#                     "Orders": "/orders",
#                     "Invoices": "/invoices",
#                     "My Account": "/me",
#                 }
#             ).get(success_url, "/me")

#         self.set_as_paid()

#         return redirect_to

#     @staticmethod
#     def get_gateway_details(args):
#         if args.order_type != "Shopping Cart":
#             return super().get_gateway_details(args)

#         cart_settings = frappe.get_doc("Webshop Settings")
#         gateway_account = cart_settings.payment_gateway_account
#         return super().get_payment_gateway_account(gateway_account)

import frappe
from frappe.utils import get_url

from erpnext.accounts.doctype.payment_request.payment_request import (
    PaymentRequest as OriginalPaymentRequest,
)


class PaymentRequest(OriginalPaymentRequest):
    def on_payment_authorized(self, status=None):
        if not status:
            return

        if status not in ("Authorized", "Completed"):
            return

        if not hasattr(frappe.local, "session"):
            return

        if frappe.local.session.user == "Guest":
            return

        cart_settings = frappe.get_doc("Webshop Settings")

        if not cart_settings.enabled:
            return

        self.set_as_paid()

        # Create Delivery Note and Sales Invoice
        self.make_invoice()

        # Get brand-specific redirect based on Sales Order
        redirect_to = self._get_brand_redirect_url()

        return redirect_to

    def _get_brand_redirect_url(self):
        """
        Get brand-specific redirect URL based on Sales Order's company.
        Maps company to brand slug for multi-brand support.
        """
        try:
            # Get Sales Order to determine company
            sales_order = frappe.get_doc("Sales Order", self.reference_name)
            company = sales_order.get("company", "")
            
            # Get customer to check for custom company preference
            customer = sales_order.get("customer")
            if customer:
                customer_company = frappe.db.get_value(
                    "Customer",
                    customer,
                    "custom_default_company"
                )
                # Use customer's default company if available
                if customer_company:
                    company = customer_company
            
            # Map company name to brand slug (must match your React route structure)
            # Company Name → Brand Slug
            company_to_brand = {
                "Rydges Wholesale": "rydges-wholesale",
                "Stockmans Wholesale": "stockman",
                "Stockman": "stockman",
                # Add more company → brand mappings as needed
            }
            
            brand_slug = company_to_brand.get(company, "rydges-wholesale")
            
            # Build brand-specific order detail URL
            redirect_url = get_url(f"/{brand_slug}/order")
            
            frappe.logger().info(
                f"Payment redirect: SO={self.reference_name}, Company={company}, Brand={brand_slug} → {redirect_url}"
            )
            
            return redirect_url
            
        except Exception as e:
            # Fallback to default brand on any error
            frappe.logger().error(f"Error getting brand redirect: {str(e)}")
            return get_url(f"/rydges-wholesale/orders/{self.reference_name}")

    def make_invoice(self):
        """
        Override to create Delivery Note first, then Sales Invoice.
        Only creates documents if make_sales_invoice is enabled.
        """
        # Check if make_sales_invoice is disabled
        if not self.get("make_sales_invoice"):
            frappe.logger().info(
                f"Skipping Delivery Note and Invoice creation for Payment Request {self.name} "
                f"because make_sales_invoice is disabled"
            )
            return

        ref_doc = frappe.get_doc(self.reference_doctype, self.reference_name)
        
        # Only process Shopping Cart orders
        if not (hasattr(ref_doc, "order_type") and ref_doc.order_type == "Shopping Cart"):
            return

        current_user = frappe.session.user
        try:
            frappe.set_user("Administrator")

            # Step 1: Create Delivery Note from Sales Order
            delivery_note = self._create_delivery_note(ref_doc)
            
            if delivery_note:
                frappe.logger().info(
                    f"Created Delivery Note {delivery_note.name} for Sales Order {ref_doc.name}"
                )
                
                # Step 2: Create Sales Invoice from Sales Order
                sales_invoice = self._create_sales_invoice(ref_doc)
                
                if sales_invoice:
                    frappe.logger().info(
                        f"Created Sales Invoice {sales_invoice.name} for Sales Order {ref_doc.name}"
                    )
            
        except Exception as e:
            frappe.log_error(
                title="Payment Request Make Invoice Error",
                message=f"Error creating DN/SI for SO {ref_doc.name}: {str(e)}"
            )
            raise
        finally:
            frappe.set_user(current_user)

    def _create_delivery_note(self, sales_order):
        """Create and submit Delivery Note from Sales Order"""
        from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
        
        # Check if Delivery Note already exists for this Sales Order
        existing_dn = frappe.db.exists(
            "Delivery Note Item",
            {"against_sales_order": sales_order.name, "docstatus": ["<", 2]}
        )
        if existing_dn:
            frappe.logger().info(
                f"Delivery Note already exists for Sales Order {sales_order.name}"
            )
            return None
        
        try:
            dn = make_delivery_note(sales_order.name)
            dn.insert()
            dn.submit()
            return dn
            
        except Exception as e:
            frappe.log_error(
                title="Delivery Note Creation Error",
                message=f"Error creating Delivery Note for SO {sales_order.name}: {str(e)}"
            )
            raise

    def _create_sales_invoice(self, sales_order):
        """Create and submit Sales Invoice from Sales Order"""
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

        existing_si = frappe.db.exists(
            "Sales Invoice Item",
            {"sales_order": sales_order.name, "docstatus": ["<", 2]}
        )
        if existing_si:
            frappe.logger().info(
                f"Sales Invoice already exists for Sales Order {sales_order.name}"
            )
            return None
        
        try:
            si = make_sales_invoice(sales_order.name)
            si.allocate_advances_automatically = True
            si.insert()
            si.submit()
            return si
            
        except Exception as e:
            frappe.log_error(
                title="Sales Invoice Creation Error",
                message=f"Error creating Sales Invoice for SO {sales_order.name}: {str(e)}"
            )
            raise

    @classmethod
    def get_gateway_details(cls, args):
        if args.get("order_type") != "Shopping Cart":
            return super(PaymentRequest, cls).get_gateway_details(args)

        cart_settings = frappe.get_doc("Webshop Settings")
        gateway_account = cart_settings.payment_gateway_account
        return super(PaymentRequest, cls).get_payment_gateway_account(gateway_account)