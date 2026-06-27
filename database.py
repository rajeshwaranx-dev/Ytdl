from pymongo import MongoClient
from config import MONGO_URI, MONGO_DB

client = MongoClient(MONGO_URI)
db     = client[MONGO_DB]

users     = db["users"]
settings  = db["settings"]


def get_user(user_id: int) -> dict:
    return users.find_one({"_id": user_id}) or {}


def upsert_user(user_id: int, data: dict):
    users.update_one({"_id": user_id}, {"$set": data}, upsert=True)


def ensure_user(user: dict):
    user_id = user["id"]
    if not users.find_one({"_id": user_id}):
        users.insert_one({
            "_id":        user_id,
            "first_name": user.get("first_name", ""),
            "last_name":  user.get("last_name", ""),
            "username":   user.get("username", ""),
            "downloads":  0,
            "unlimited":  False,
            "referrals":  0,
            "referred_by": None,
        })


def increment_download(user_id: int) -> int:
    users.update_one({"_id": user_id}, {"$inc": {"downloads": 1}})
    return users.find_one({"_id": user_id}).get("downloads", 0)


def get_download_count(user_id: int) -> int:
    return users.find_one({"_id": user_id}, {"downloads": 1}).get("downloads", 0) if users.find_one({"_id": user_id}) else 0


def is_unlimited(user_id: int) -> bool:
    doc = users.find_one({"_id": user_id}, {"unlimited": 1})
    return doc.get("unlimited", False) if doc else False


def set_unlimited(user_id: int):
    users.update_one({"_id": user_id}, {"$set": {"unlimited": True}})


def get_referral_count(user_id: int) -> int:
    doc = users.find_one({"_id": user_id}, {"referrals": 1})
    return doc.get("referrals", 0) if doc else 0


def process_referral(new_user_id: int, referrer_id: int) -> bool:
    from config import REFERRALS_NEEDED
    doc = users.find_one({"_id": new_user_id})
    if not doc or doc.get("referred_by"):
        return False
    users.update_one({"_id": new_user_id}, {"$set": {"referred_by": referrer_id}})
    users.update_one({"_id": referrer_id},  {"$inc": {"referrals": 1}})
    referrer = users.find_one({"_id": referrer_id})
    if referrer and referrer.get("referrals", 0) >= REFERRALS_NEEDED and not referrer.get("unlimited"):
        set_unlimited(referrer_id)
        return True
    return False


def get_stats() -> dict:
    total_users     = users.count_documents({})
    total_downloads = sum(u.get("downloads", 0) for u in users.find({}, {"downloads": 1}))
    limited_users   = users.count_documents({"unlimited": False})
    unlimited_users = users.count_documents({"unlimited": True})
    total_referrals = sum(u.get("referrals", 0) for u in users.find({}, {"referrals": 1}))
    return {
        "total_users":     total_users,
        "total_downloads": total_downloads,
        "limited_users":   limited_users,
        "unlimited_users": unlimited_users,
        "total_referrals": total_referrals,
    }


def get_limit_enabled() -> bool:
    doc = settings.find_one({"_id": "limit"})
    return doc.get("enabled", True) if doc else True


def set_limit_enabled(val: bool):
    settings.update_one({"_id": "limit"}, {"$set": {"enabled": val}}, upsert=True)

def get_limit_value() -> int:
    doc = settings.find_one({"_id": "limit"})
    return doc.get("value", 100) if doc else 100


def set_limit(enabled: bool, value: int = None):
    update = {"enabled": enabled}
    if value is not None:
        update["value"] = value
    settings.update_one({"_id": "limit"}, {"$set": update}, upsert=True)
