"""Graph schema: labels, relationship types and indexes.

Kept deliberately small so it can be explained in a demo. See README "Graph schema".
"""

NODE_LABELS = [
    "Retailer",
    "Product",
    "Distributor",
    "Warehouse",
    "Inventory",
    "Order",
    "Delivery",
    "SalesVisit",
    "Promotion",
]

# (source label, relationship, target label, meaning)
RELATIONSHIPS = [
    ("Retailer", "LISTS", "Product", "Product is part of the retailer's assortment"),
    ("Retailer", "SERVED_BY", "Distributor", "Distributor responsible for replenishing the retailer"),
    ("Distributor", "SOURCES_FROM", "Warehouse", "Replenishment route; `priority` 1 = primary"),
    ("Warehouse", "HOLDS", "Inventory", "Stock snapshot held at a warehouse"),
    ("Retailer", "HOLDS", "Inventory", "Shelf/back-room stock snapshot held at a retailer"),
    ("Inventory", "OF_PRODUCT", "Product", "Which product the snapshot counts"),
    ("Order", "FOR_RETAILER", "Retailer", "Replenishment order destination"),
    ("Order", "FOR_PRODUCT", "Product", "Ordered product"),
    ("Order", "ASSIGNED_TO", "Distributor", "Distributor fulfilling the order"),
    ("Order", "ALLOCATED_FROM", "Warehouse", "Warehouse the order was allocated/dispatched from"),
    ("Order", "RESERVES", "Inventory", "Order holds a reservation (`quantity`) on warehouse stock"),
    ("Delivery", "FULFILLS", "Order", "Shipment executing the order"),
    ("SalesVisit", "AT_RETAILER", "Retailer", "Field visit location"),
    ("SalesVisit", "OBSERVED", "Product", "Shelf observation (`shelf_status`) during the visit"),
    ("Promotion", "PROMOTES", "Product", "Trade promotion on the product"),
]

INDEX_STATEMENTS = [f"CREATE INDEX FOR (n:{label}) ON (n.id)" for label in NODE_LABELS]
