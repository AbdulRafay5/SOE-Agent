from pytrends.request import TrendReq
import time

pytrends = TrendReq(hl='en-US', tz=360, retries=3, backoff_factor=0.5)

keyword = "iPhone"
pytrends.build_payload([keyword], timeframe='now 7-d')

time.sleep(2)
related = pytrends.related_queries()

rising_df = related[keyword]['rising']
rising_keywords = rising_df['query'].tolist()

print(rising_keywords)