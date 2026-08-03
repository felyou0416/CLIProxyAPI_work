from backend.city_alias_map import city_alias_map, CITY_ALIAS_MAP

def test_city_alias_map_shantou_chaozhou():
    assert city_alias_map["汕头"] == "SHANTOU"
    assert city_alias_map["Shantou"] == "SHANTOU"
    assert city_alias_map["潮州"] == "CHAOZHOU"
    assert city_alias_map["Chaozhou"] == "CHAOZHOU"
    assert CITY_ALIAS_MAP["汕头"] == "SHANTOU"
    assert CITY_ALIAS_MAP["潮州"] == "CHAOZHOU"
