"""Giữ thứ tự email, bỏ trùng và tách một email trên một dòng công ty."""
import re

PATTERN = r"(?<![\w.*])([A-Za-z0-9.!#$%&'+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+)"

def emails(value):
    result, seen = [], set()
    for match in re.finditer(PATTERN, str(value)):
        address = match.group(1).rstrip('.')
        if address.casefold() not in seen:
            result.append(address)
            seen.add(address.casefold())
    return result

def split_company_emails(rows):
    result = []
    for row in rows:
        addresses = emails(row[19])
        for address in addresses or [row[19]]:
            copy = list(row)
            copy[19] = address
            result.append(copy)
    return result
