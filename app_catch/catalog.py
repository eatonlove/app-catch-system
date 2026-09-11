"""Only route samples observed in the logged-in DianDian UI are enabled."""
CATALOG = {
 'ios-us-tools-grossing': {'market':'appstore','country':'US','store':'appstore','device':'iphone','category':'工具','chart':'grossing','path':'/rank/ios/1-1-140-24-4','title':['美国','工具','畅销榜']},
 'gp-us-overall-grossing': {'market':'googleplay','country':'US','store':'googleplay','device':'android','category':'总榜','chart':'grossing','path':'/rank/googleplay/11-4-0-24-2','title':['美国','畅销榜','GooglePlay']},
 'huawei-tools': {'market':'android_cn','country':'CN','store':'huawei','device':'android','category':'实用工具','chart':'free','path':'/rank/android/2-201-0-75-901991','title':['华为','实用工具']},
 'harmony-overall': {'market':'android_cn','country':'CN','store':'harmony','device':'harmony','category':'全部应用','chart':'free','path':'/rank/android/9999-1-0-75-0','title':['鸿蒙','应用排行榜']},
}
CONTEXT_KEYS = ('market','country','store','device','category','chart')
def context_for(name, day):
    return dict({k:CATALOG[name][k] for k in CONTEXT_KEYS}, data_date=day)
