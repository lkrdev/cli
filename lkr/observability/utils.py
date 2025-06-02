import random
import re
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from pydash import set_

from lkr.logger import logger

MAX_SESSION_LENGTH = 2592000

PERMISSIONS = [
    "access_data",
    "see_user_dashboards",
    "see_lookml_dashboards",
    "see_looks",
    "explore",
]


def get_user_id() -> str:
    return "embed-" + str(random.randint(1000000000, 9999999999))


def invalid_attribute_format(attr: str) -> bool:
    logger.error(f"Invalid attribute: {attr}")
    return False


def check_random_int_format(val: str) -> Tuple[bool, str | None]:
    if re.match(r"^random\.randint\(\d+,\d+\)$", val):
        # check if #  random.randint(0, 1000000) 0 and 100000 are integers
        numbers = re.findall(r"\d+", val.split("(")[1])
        if len(numbers) == 2:
            return True, str(
                random.randint(
                    int(numbers[0]),
                    int(numbers[1]),
                )
            )
        else:
            return False, None
    else:
        return False, None


def format_attributes(
    attributes: List[str] = [], seperator: str = ":"
) -> Dict[str, str]:
    formatted_attributes: Dict[str, str] = {}
    if attributes:
        for attr in attributes:
            valid = True
            split_attr = [x.strip() for x in attr.split(seperator) if x.strip()]
            if len(split_attr) == 2:
                val = split_attr[1]
                # regex to check if for string random.randint(0,1000000)
                is_valid, val = check_random_int_format(val)
                if is_valid:
                    set_(split_attr, 1, val)
                    set_(formatted_attributes, [split_attr[0]], split_attr[1])
                else:
                    valid = False
            else:
                valid = False
            if valid:
                formatted_attributes[split_attr[0]] = split_attr[1]
            else:
                invalid_attribute_format(attr)

    return formatted_attributes


def now():
    return datetime.now(timezone.utc)


def ms_diff(start: datetime):
    return int((now() - start).total_seconds() * 1000)
