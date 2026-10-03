"""Domain definitions: rules, system-under-test (SUT) with injectable bugs, test scenarios."""
SEV = {"Critical": 0, "High": 1, "Medium": 2}

def _chk(checks):
    def sut(i, b=frozenset()):
        for rule, f in checks:
            if f(i, b):
                return "REJECT:" + rule
        return "OK"
    return sut

def _cases(base, rule, rows):
    return [(rule, lbl, {**base, **o}) for lbl, o in rows]

# ---------------- Banking: fund transfer ----------------
def _dec(a): return abs(a * 100 - round(a * 100)) > 1e-6
def _lim(i, b):
    L = {"UPI": 100000, "IMPS": 500000}.get(i["channel"])
    if L is None: return False
    return i["amount"] >= L if ("UPI_BOUNDARY" in b and i["channel"] == "UPI") else i["amount"] > L
BANK = _chk([
    ("BR-06", lambda i, b: "DECIMALS" not in b and _dec(i["amount"])),
    ("BR-05", lambda i, b: "RECEIVER_FROZEN" not in b and i["frozen"]),
    ("BR-03", lambda i, b: i["amount"] >= i["balance"] if "BALANCE_BOUNDARY" in b else i["amount"] > i["balance"]),
    ("BR-02", _lim),
    ("BR-07", lambda i, b: "DAILY_LIMIT" not in b and i["daily"] + i["amount"] > 1000000)])
BB = dict(amount=1000, balance=10**7, channel="NEFT", frozen=False, daily=0)

# ---------------- E-commerce: checkout ----------------
SHOP = _chk([
    ("EC-01", lambda i, b: i["qty"] < (0 if "QTY_ZERO" in b else 1)),
    ("EC-02", lambda i, b: i["qty"] >= i["stock"] if "STOCK_BOUNDARY" in b else i["qty"] > i["stock"]),
    ("EC-03", lambda i, b: (i["disc"] >= 50 if "DISCOUNT_CAP" in b else i["disc"] > 50) or ("DISCOUNT_NEG" not in b and i["disc"] < 0))])
SB = dict(qty=1, stock=10, disc=0)

# ---------------- Healthcare: prescription ----------------
def _dose(i, b):
    mx = 500 if ("CHILD_LIMIT" in b or i["age"] >= 12) else 250
    return i["dose"] >= mx if "DOSE_BOUNDARY" in b else i["dose"] > mx
HEALTH = _chk([
    ("HC-02", lambda i, b: i["age"] < 0 or (i["age"] >= 120 if "AGE_RANGE" in b else i["age"] > 120)),
    ("HC-03", lambda i, b: "ALLERGY_IGNORED" not in b and i["allergy"]),
    ("HC-01", _dose)])
HB = dict(age=30, dose=100, allergy=False)

DOMAINS = {
 "banking": dict(title="Retail Banking - Fund Transfer", sut=BANK,
  rules={"BR-02": ("Critical", "UPI max Rs 1,00,000 and IMPS max Rs 5,00,000 per transaction; NEFT has no per-transaction limit."),
         "BR-03": ("Critical", "A transfer must not exceed the available balance."),
         "BR-05": ("Critical", "Transfers to a frozen or inactive account must be rejected."),
         "BR-06": ("Medium", "Amount may have at most two decimal places."),
         "BR-07": ("High", "Total transferred in a day must not exceed Rs 10,00,000.")},
  bugs={"UPI_BOUNDARY": "UPI limit check uses >= instead of >", "BALANCE_BOUNDARY": "Balance check rejects transfer of the entire balance",
        "RECEIVER_FROZEN": "Frozen status of the receiver is never checked", "DECIMALS": "More than 2 decimal places is accepted",
        "DAILY_LIMIT": "Daily limit ignores amount already transferred today"},
  cases=(_cases(BB, "BR-02", [("UPI at limit", dict(channel="UPI", amount=100000)), ("UPI just above limit", dict(channel="UPI", amount=100000.01)),
          ("IMPS at limit", dict(channel="IMPS", amount=500000)), ("IMPS just above limit", dict(channel="IMPS", amount=500000.01)), ("NEFT large amount", dict(amount=600000))])
        + _cases(BB, "BR-03", [("Amount equals balance", dict(amount=5000, balance=5000)), ("Amount above balance", dict(amount=5000.01, balance=5000))])
        + _cases(BB, "BR-05", [("Frozen receiver", dict(frozen=True)), ("Active receiver", dict(frozen=False))])
        + _cases(BB, "BR-06", [("Two decimals", dict(amount=10.55)), ("Three decimals", dict(amount=10.555))])
        + _cases(BB, "BR-07", [("Daily total at cap", dict(amount=100000, daily=900000)), ("Daily total over cap", dict(amount=100000, daily=900001))])),
  space=dict(amount=lambda r: round(r.uniform(1, 1200000), 2), balance=lambda r: round(r.uniform(1, 1500000), 2),
             channel=lambda r: r.choice(["UPI", "IMPS", "NEFT"]), frozen=lambda r: r.random() < 0.2, daily=lambda r: round(r.uniform(0, 1000000), 2))),
 "ecommerce": dict(title="E-Commerce - Checkout", sut=SHOP,
  rules={"EC-01": ("High", "Order quantity must be at least 1."), "EC-02": ("Critical", "Order quantity must not exceed available stock."),
         "EC-03": ("High", "Discount must be between 0% and 50% inclusive.")},
  bugs={"QTY_ZERO": "Quantity 0 is accepted", "STOCK_BOUNDARY": "Ordering exactly the available stock is rejected",
        "DISCOUNT_CAP": "Discount of exactly 50% is rejected", "DISCOUNT_NEG": "Negative discount is accepted"},
  cases=(_cases(SB, "EC-01", [("Quantity 1", dict(qty=1)), ("Quantity 0", dict(qty=0))])
        + _cases(SB, "EC-02", [("Quantity equals stock", dict(qty=10)), ("Quantity above stock", dict(qty=11))])
        + _cases(SB, "EC-03", [("No discount", dict(disc=0)), ("Discount at cap", dict(disc=50)), ("Discount above cap", dict(disc=50.01)), ("Negative discount", dict(disc=-1))])),
  space=dict(qty=lambda r: r.randint(0, 15), stock=lambda r: r.randint(1, 12), disc=lambda r: round(r.uniform(-10, 70), 1))),
 "healthcare": dict(title="Healthcare - Prescription Check", sut=HEALTH,
  rules={"HC-01": ("Critical", "Dose must not exceed 250 mg (age under 12) or 500 mg (age 12 and above)."),
         "HC-02": ("Medium", "Patient age must be between 0 and 120 inclusive."), "HC-03": ("Critical", "Prescribing a drug with a recorded allergy must be rejected.")},
  bugs={"CHILD_LIMIT": "Child patients are given the adult dose limit", "DOSE_BOUNDARY": "A dose exactly at the maximum is rejected",
        "AGE_RANGE": "Age 120 is rejected", "ALLERGY_IGNORED": "Allergy flag is never checked"},
  cases=(_cases(HB, "HC-01", [("Child at max dose", dict(age=11, dose=250)), ("Child above max dose", dict(age=11, dose=251)),
          ("Adult at max dose", dict(age=12, dose=500)), ("Adult above max dose", dict(age=12, dose=501))])
        + _cases(HB, "HC-02", [("Age 120", dict(age=120)), ("Age 121", dict(age=121)), ("Negative age", dict(age=-1))])
        + _cases(HB, "HC-03", [("Allergy recorded", dict(allergy=True)), ("No allergy", dict(allergy=False))])),
  space=dict(age=lambda r: r.randint(-2, 125), dose=lambda r: round(r.uniform(1, 600), 1), allergy=lambda r: r.random() < 0.2)),
  # ---------------- Food delivery: order validation ----------------
  "food_delivery": dict(title="Food Delivery - Order Validation", sut=_chk([
   ("FD-01", lambda i, b: i["qty"] < (0 if "FOOD_QTY_ZERO" in b else 1)),
   ("FD-02", lambda i, b: i["qty"] >= i["stock"] if "FOOD_STOCK_BOUNDARY" in b else i["qty"] > i["stock"]),
   ("FD-03", lambda i, b: i["distance"] >= 20 if "FOOD_DISTANCE_BOUNDARY" in b else i["distance"] > 20),
   ("FD-04", lambda i, b: i["subtotal"] <= 100 if "FOOD_MINIMUM_BOUNDARY" in b else i["subtotal"] < 100)]),
   rules={"FD-01": ("High", "An order must contain at least one item."),
          "FD-02": ("Critical", "Item quantity must not exceed available restaurant stock."),
          "FD-03": ("High", "Delivery distance must be 20 km or less."),
          "FD-04": ("Medium", "The order subtotal must be at least Rs 100.")},
   bugs={"FOOD_QTY_ZERO": "An order quantity of zero is accepted",
         "FOOD_STOCK_BOUNDARY": "Ordering exactly the available stock is rejected",
         "FOOD_DISTANCE_BOUNDARY": "Delivery exactly 20 km away is rejected",
         "FOOD_MINIMUM_BOUNDARY": "An order at the Rs 100 minimum is rejected"},
   cases=(_cases(dict(qty=1, stock=10, distance=5, subtotal=500), "FD-01",
           [("One item", dict(qty=1)), ("Zero items", dict(qty=0))])
         + _cases(dict(qty=1, stock=10, distance=5, subtotal=500), "FD-02",
           [("Quantity equals stock", dict(qty=10)), ("Quantity exceeds stock", dict(qty=11))])
         + _cases(dict(qty=1, stock=10, distance=5, subtotal=500), "FD-03",
           [("Delivery at distance limit", dict(distance=20)), ("Delivery beyond distance limit", dict(distance=20.1))])
         + _cases(dict(qty=1, stock=10, distance=5, subtotal=500), "FD-04",
           [("Subtotal at minimum", dict(subtotal=100)), ("Subtotal below minimum", dict(subtotal=99.99))])),
   space=dict(qty=lambda r: r.randint(0, 15), stock=lambda r: r.randint(1, 12),
              distance=lambda r: round(r.uniform(0, 30), 1), subtotal=lambda r: round(r.uniform(0, 500), 2))),
  # ---------------- Travel booking: passenger and baggage validation ----------------
  "travel": dict(title="Travel Booking - Passenger and Baggage Validation", sut=_chk([
   ("TR-01", lambda i, b: i["passengers"] < (0 if "TRAVEL_PASSENGER_ZERO" in b else 1)),
   ("TR-02", lambda i, b: i["passengers"] >= i["seats"] if "TRAVEL_SEAT_BOUNDARY" in b else i["passengers"] > i["seats"]),
   ("TR-03", lambda i, b: i["baggage"] >= 15 if "TRAVEL_BAGGAGE_BOUNDARY" in b else i["baggage"] > 15),
   ("TR-04", lambda i, b: i["age"] < 0 or (i["age"] >= 120 if "TRAVEL_AGE_RANGE" in b else i["age"] > 120))]),
   rules={"TR-01": ("High", "A booking must include at least one passenger."),
          "TR-02": ("Critical", "The number of passengers must not exceed available seats."),
          "TR-03": ("Medium", "Checked baggage must not exceed 15 kg per passenger."),
          "TR-04": ("Medium", "Passenger age must be between 0 and 120 inclusive.")},
   bugs={"TRAVEL_PASSENGER_ZERO": "A booking with zero passengers is accepted",
         "TRAVEL_SEAT_BOUNDARY": "Booking all remaining seats is rejected",
         "TRAVEL_BAGGAGE_BOUNDARY": "Baggage of exactly 15 kg is rejected",
         "TRAVEL_AGE_RANGE": "A passenger aged 120 is rejected"},
   cases=(_cases(dict(passengers=1, seats=10, baggage=10, age=30), "TR-01",
           [("One passenger", dict(passengers=1)), ("Zero passengers", dict(passengers=0))])
         + _cases(dict(passengers=1, seats=10, baggage=10, age=30), "TR-02",
           [("Passengers equal available seats", dict(passengers=10)), ("Passengers exceed available seats", dict(passengers=11))])
         + _cases(dict(passengers=1, seats=10, baggage=10, age=30), "TR-03",
           [("Baggage at limit", dict(baggage=15)), ("Baggage above limit", dict(baggage=15.1))])
         + _cases(dict(passengers=1, seats=10, baggage=10, age=30), "TR-04",
           [("Age 120", dict(age=120)), ("Age 121", dict(age=121)), ("Negative age", dict(age=-1))])),
   space=dict(passengers=lambda r: r.randint(0, 12), seats=lambda r: r.randint(1, 10),
              baggage=lambda r: round(r.uniform(0, 25), 1), age=lambda r: r.randint(-2, 125))),
 # ---------------- Telecom: mobile plan validation ----------------
 "telecom": dict(title="Telecom - Mobile Plan Validation", sut=_chk([
   ("TC-01", lambda i, b: "TELECOM_NEGATIVE_USAGE" not in b and i["usage"] < 0),
   ("TC-02", lambda i, b: i["usage"] >= i["data_limit"] if "TELECOM_DATA_BOUNDARY" in b else i["usage"] > i["data_limit"]),
   ("TC-03", lambda i, b: "TELECOM_STATUS_IGNORED" not in b and not i["active"])]),
   rules={"TC-01": ("High", "Mobile data usage cannot be negative."),
          "TC-02": ("Critical", "Data usage must not exceed the customer's plan limit."),
          "TC-03": ("High", "Only active customer accounts may use mobile services.")},
   bugs={"TELECOM_NEGATIVE_USAGE": "Negative data usage is accepted",
         "TELECOM_DATA_BOUNDARY": "Usage exactly at the plan limit is rejected",
         "TELECOM_STATUS_IGNORED": "Inactive customer status is not checked"},
   cases=(_cases(dict(usage=10, data_limit=100, active=True), "TC-01",
           [("Zero usage", dict(usage=0)), ("Negative usage", dict(usage=-0.1))])
         + _cases(dict(usage=10, data_limit=100, active=True), "TC-02",
           [("Usage at plan limit", dict(usage=100)), ("Usage above plan limit", dict(usage=100.1))])
         + _cases(dict(usage=10, data_limit=100, active=True), "TC-03",
           [("Active account", dict(active=True)), ("Inactive account", dict(active=False))])),
   space=dict(usage=lambda r: round(r.uniform(-5, 150), 1), data_limit=lambda r: r.choice([50, 100, 200]),
              active=lambda r: r.random() < 0.9)),
 # ---------------- Hotel booking: reservation validation ----------------
 "hotel": dict(title="Hotel Booking - Reservation Validation", sut=_chk([
   ("HT-01", lambda i, b: i["nights"] < (0 if "HOTEL_ZERO_NIGHTS" in b else 1)),
   ("HT-02", lambda i, b: i["rooms"] >= i["available"] if "HOTEL_ROOM_BOUNDARY" in b else i["rooms"] > i["available"]),
   ("HT-03", lambda i, b: i["guests"] >= i["rooms"] * 2 if "HOTEL_CAPACITY_BOUNDARY" in b else i["guests"] > i["rooms"] * 2),
   ("HT-04", lambda i, b: i["nights"] > (31 if "HOTEL_STAY_LIMIT_IGNORED" in b else 30))]),
   rules={"HT-01": ("High", "A hotel reservation must be for at least one night."),
          "HT-02": ("Critical", "The number of rooms booked must not exceed available rooms."),
          "HT-03": ("High", "A room accommodates at most two guests."),
          "HT-04": ("Medium", "A single reservation cannot exceed 30 nights.")},
   bugs={"HOTEL_ZERO_NIGHTS": "A zero-night reservation is accepted",
         "HOTEL_ROOM_BOUNDARY": "Booking exactly all available rooms is rejected",
         "HOTEL_CAPACITY_BOUNDARY": "A booking at the exact room guest capacity is rejected",
         "HOTEL_STAY_LIMIT_IGNORED": "The maximum stay length is not enforced"},
   cases=(_cases(dict(nights=2, rooms=1, available=10, guests=2), "HT-01",
           [("One-night stay", dict(nights=1)), ("Zero-night stay", dict(nights=0))])
         + _cases(dict(nights=2, rooms=1, available=10, guests=2), "HT-02",
           [("Rooms equal availability", dict(rooms=10)), ("Rooms exceed availability", dict(rooms=11))])
         + _cases(dict(nights=2, rooms=1, available=10, guests=2), "HT-03",
           [("Guests at room capacity", dict(guests=2)), ("Guests above room capacity", dict(guests=3))])
         + _cases(dict(nights=2, rooms=1, available=10, guests=2), "HT-04",
           [("Stay at maximum length", dict(nights=30)), ("Stay above maximum length", dict(nights=31))])),
   space=dict(nights=lambda r: r.randint(0, 40), rooms=lambda r: r.randint(1, 12),
              available=lambda r: r.randint(1, 10), guests=lambda r: r.randint(1, 30))),
}
