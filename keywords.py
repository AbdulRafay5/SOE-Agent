existing_keywords = [
    "Pharmacy Management System in Rawalpindi",
    "Pharmacy Management System in Lahore",
    "Pharmacy Management System in Karachi",
    "Pharmacy Management System in Islamabad",
    "POS Software for Retail Store",
    "Free POS System",
    "FBR Digital Invoicing System Software in Pakistan",
    "SRB POS Integration in Pakistan",
]

industries = [
    "Restaurant", "Stationery Shop", "Auto Spare Parts", "Electronics Shop",
    "Gym", "Clothing Store", "Wholesale Business", "Salon", "Grocery Store", "Bakery"
]

cities = [
    "Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad",
    "Multan", "Peshawar", "Quetta", "Sialkot", "Gujranwala"
]

tax_authorities = [
    "FBR", "SRB", "PRA", "KPRA", "BRA"
]

software_types = [
    "POS Software", "Digital Invoicing Software", "Pharmacy Management Software",
    "Accounting Software", "ERP System", "Payroll Software"
]

new_keywords = []

# Software type + industry (e.g. "POS Software for Gym")
for software in software_types:
    for industry in industries:
        new_keywords.append(f"{software} for {industry}")

# Software type + city (e.g. "Pharmacy Management Software in Faisalabad")
for software in software_types:
    for city in cities:
        new_keywords.append(f"{software} in {city}")

# Tax authority + integration (e.g. "PRA POS Integration in Pakistan")
for authority in tax_authorities:
    new_keywords.append(f"{authority} POS Integration in Pakistan")
    new_keywords.append(f"{authority} Digital Invoicing Integration Guide")

all_keywords = existing_keywords + new_keywords

PRICING_URL = "https://sadahisab.com/pricing-plan/"
CONTACT_URL = "https://sadahisab.com/contact-us/"

industry_links = {
    "Restaurant": "https://sadahisab.com/industries/restaurant-pos-system-software/",
    "Stationery Shop": "https://sadahisab.com/industries/best-pos-software-for-stationery-shops/",
    "Auto Spare Parts": "https://sadahisab.com/industries/pos-software-for-auto-spare-parts/",
    "Electronics Shop": "https://sadahisab.com/industries/pos-software-for-electronics-shop/",
    "Gym": "https://sadahisab.com/industries/pos-software-for-gym/",
    "Clothing Store": "https://sadahisab.com/industries/pos-software-for-clothing-store/",
    "Wholesale Business": "https://sadahisab.com/industries/pos-software-for-wholesale-business/",
    "Salon": "https://sadahisab.com/industries/pos-software-for-salon/",
    "Grocery Store": "https://sadahisab.com/industries/pos-software-for-grocery-store/",
    "Bakery": "https://sadahisab.com/industries/pos-software-for-bakery/",
}

keyword_links = {keyword: PRICING_URL for keyword in all_keywords}
for software in software_types:
    for industry, url in industry_links.items():
        keyword_links[f"{software} for {industry}"] = url

if __name__ == "__main__":
    print(f"Total keywords: {len(all_keywords)}")
    for kw in all_keywords:
        print(kw)