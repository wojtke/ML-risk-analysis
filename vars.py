from datetime import timedelta
from ciso8601 import parse_datetime

class Vars:
	SYMBOL = 'BTC'
	INTERVAL = '15m'

	'''
	WINDOWS = [ [parse_datetime("2020"+"02"+"23"), timedelta(days=15)], 
                [parse_datetime("2020"+"04"+"10"), timedelta(days=15)], ] 
	'''

	WINDOWS = [ [parse_datetime("2020"+"06"+"01"), timedelta(days=29)] ] 

	main_path = 'D:/PROJEKTY/Python/ML risk analysis/'