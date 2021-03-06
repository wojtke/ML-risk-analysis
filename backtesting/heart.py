from datetime import datetime, timedelta
from ciso8601 import parse_datetime
import numpy as np

import pandas as pd
from datetime import datetime
import statistics as s

import sys
sys.path.append("..")
from data_processing import Preprocessor

iv_sec = {'1m':60, '3m':60*3, '5m':60*5, '15m':60*15, '30m':60*30, '1h':60*60, '2h':60*60*2, '4h':60*60*4, '8h':60*60*8, '1d':60*60*24, '3d':60*60*24*3, '1w':60*60*24*7}

class Account():
    def __init__(self, leverage, order_size, pyramid_max, FEE, liq_bump, start_balance, MODEL, secondary_model=None):
        self.ORDER_SIZE = order_size
        self.pyramid_max = pyramid_max
        self.awaiting_orders = []

        self.MODEL = MODEL
        self.leverage = leverage
        self.FEE = FEE
        self.liq_bump = liq_bump

        self.start_balance = start_balance
        self.balance = start_balance
        self.position = 0
        self.pos_fee = 0
        self.margin = 0
        self.entry_price = 0
        self.time = 0 
        self.PNL = 0

        self.trade = s.Trade()
        self.pyramid = 0
        self.pyramid_awaiting = 0


        preprocessor = Preprocessor()

        self.klines = preprocessor.klines_load()
        preprocessor.repreprocess(self.MODEL)

        self.symbol = preprocessor.SYMBOL
        self.interval = preprocessor.INTERVAL
        self.k_i = preprocessor.PAST_SEQ_LEN + 1
        self.kline_limit = preprocessor.PAST_SEQ_LEN + 1

        self.pred_df = preprocessor.pred_df

        if secondary_model:
            self.secondary_model = secondary_model
            preprocessor_2 = Preprocessor(klines='futures')
            preprocessor_2.repreprocess(secondary_model, do_not_use_ready=True)
            self.pred_df_2 = preprocessor_2.pred_df
        else:
            self.secondary_model= None

        #self.klines = self.klines.reset_index()
        #self.klines = self.klines.drop(columns=["index"])

        print(f"Loaded klines starting from {datetime.fromtimestamp(int(self.klines.values[0][0])/1000)}"
            + f" ending on {datetime.fromtimestamp(int(self.klines.values[-1][0]/1000))}")

    def tick(self):
        if self.k_i+1==len(self.klines.index):
            print(f"KONIEC, roi: {round(self.balance/self.start_balance*100-100,2)}%")
            return pd.DataFrame(), None
        else: 
            self.k_i+=1

        if self.klines.index[self.k_i-1]+1 != self.klines.index[self.k_i]:
            print("jump")
            self.close("SHORT", cancel_awaiting_orders=True)
            self.close("LONG", cancel_awaiting_orders=True)            
            self.k_i+=self.kline_limit

        candles = self.klines[self.k_i-1:self.k_i] # kiedys bylo self.klines[self.k_i-self.kline_limit:self.k_i]

        self.price = candles.values[-1][4]
        self.time = candles.values[-1][0]

        high = candles.values[-1][2]
        low = candles.values[-1][3]

        for i, (side, price) in enumerate(self.awaiting_orders[::-1]):
            if side == 'LONG':
                if low<price:
                    self.pyramid_awaiting-=1
                    self.awaiting_orders.pop()
                    self.open(side, price)
            elif side == 'SHORT':
                if high>price:
                    self.pyramid_awaiting-=1
                    self.awaiting_orders.pop()
                    self.open(side, price)
            else:
                "Cos nie tak z arumentem side"
                self.pyramid_awaiting-=1
                self.awaiting_orders.pop()       

        #calculating pnl and checking for liq
        self.PNL = self.position*(self.price - self.entry_price)

        if self.entry_price != 0:   
            self.change = self.price/self.entry_price - 1
        else:
            self.change = 0


        if self.position>0: #LONG
            PNL_pct_high = (self.position*(high - self.entry_price) - (self.pos_fee + self.FEE*self.position*high))/self.margin
            PNL_pct_low = (self.position*(low - self.entry_price) - (self.pos_fee + self.FEE*self.position*low))/self.margin

            if PNL_pct_low<-1+self.liq_bump: #nie jest dokladne bo wlicza juz fees a normalnie to by bylo osobne
                self.liq()

            self.trade.update_pnl(PNL_pct_high, PNL_pct_low)

        elif self.position<0: #SHORT
            PNL_pct_low = (self.position*(high - self.entry_price) - (self.pos_fee + self.FEE*self.position*high))/self.margin
            PNL_pct_high = (self.position*(low - self.entry_price) - (self.pos_fee + self.FEE*self.position*low))/self.margin

            if PNL_pct_low<-1+self.liq_bump:
                self.liq()

            self.trade.update_pnl(PNL_pct_high, PNL_pct_low)

        pred = self.pred_df['preds'][self.klines.index[self.k_i-1]]
        if self.secondary_model:
            pred_2 = self.pred_df_2['preds'][self.klines.index[self.k_i-1]]
            return candles, pred, pred_2
        return candles, pred

    def close(self, side, cancel_awaiting_orders=True):
        if self.position<0 and side == "SHORT" or self.position>0 and side == "LONG":
            #print("Closing", side)
            self.pos_fee+=abs(self.FEE*self.position*self.price)
            self.balance+=self.PNL - self.pos_fee
            self.trade.close(self.price, self.time, (self.PNL - self.pos_fee)/self.margin)

            self.position = 0
            self.entry_price = 0
            self.margin = 0
            self.pos_fee = 0
            self.PNL = 0
            self.pyramid = 0
        else:
            #print(f'No {side} to close')
            pass

        if cancel_awaiting_orders==True:
            for i, (awaiting_side, price) in enumerate(self.awaiting_orders[::-1]):
                if awaiting_side == side:
                    self.awaiting_orders.pop(-i)
                    self.pyramid_awaiting-=1



    def create_order(self, side, price=None):
        if self.pyramid+self.pyramid_awaiting>=self.pyramid_max:
            #print(f"Would be {side} but max pyramid ({self.pyramid_max})")
            return 0

        if price:
            self.awaiting_orders.append((side, price))
            self.pyramid_awaiting+=1
        else:
            self.open(side, self.price)


    def open(self, side, price): #Nie ma przebijania, nie ma zmniejszania poz, tylko nowa pozycja lub dokladam
        if self.pyramid+self.pyramid_awaiting>=self.pyramid_max:
            #print(f"Would be {side} but max pyramid ({self.pyramid_max})")
            return 0

        quantity = self.order_size(side)

        if self.position==0:
            margin = abs(self.position + quantity)*price/self.leverage
            entry = price
        elif self.position*quantity>0:
            margin = self.margin + abs(quantity*price/self.leverage)
            entry = (self.position*self.entry_price + quantity*price)/(self.position+quantity)
        else:
            print("Nowa pozycja albo dokladka, nic innego nie przewiduje")

        if margin <= self.balance:
            self.position+=quantity
            self.margin = margin
            self.pos_fee += abs(self.FEE*quantity*price)
            self.entry_price = entry
            self.pyramid+=1

            if self.position>0:
                liq = (self.entry_price)*(1-1/self.leverage+self.liq_bump)
            elif self.position<0:
                liq = (self.entry_price)*(1+1/self.leverage+self.liq_bump)

            if self.pyramid==1:
                self.trade.open(side=side)
            self.trade.add(price, self.time, amount=abs(quantity)*price/(self.leverage*self.balance), liq=liq)

        else:
            print("Za duzy order")

    def liq(self):
        print("Liq")
        self.position = 0
        self.entry_price = 0
        self.balance -= self.margin
        self.margin = 0
        self.pos_fee = 0
        self.PNL = 0
        self.pyramid = 0

        self.trade.liquidate(self.time) 

    def order_size(self, side):
        if side == "LONG":
            return self.ORDER_SIZE*(self.balance-self.margin)*self.leverage/self.price
        elif side == "SHORT":
            return -self.ORDER_SIZE*(self.balance-self.margin)*self.leverage/self.price
        else:
            print("order wrong side")

    def additional_interval(self, interval):
        d = f"RAW_DATA/Binance_{self.symbol}USDT_{interval}.json"
        self.klines_additional = pd.read_json(d)
        self.klines_additional = self.klines_additional.set_index(0)

    def get_additional_price(self, interval):
        time=int(self.time - 1000*iv_sec[interval] - self.time%(1000*iv_sec[interval]))
        try:
            to_return = self.klines_additional[4].loc[time-100:time]
        except:
            #print("Nie mozna znalezc dodatkowej swiecy dziennej")
            return self.price
        return to_return

    def print_details(self):
        print("-----------------")
        print("time : ", datetime.fromtimestamp(self.time/1000))
        print("balance : ", self.balance)
        print("margin : ", self.margin)
        print("position : ", self.position)
        print("pos_fee : ", self.pos_fee)
        print("entry_price : ", self.entry_price)
        print("pnl : ", self.PNL)
        print("pyramid : ", self.pyramid)
        print("Awaiting_orders: ")
        for side, price in self.awaiting_orders:
            print(side, price)

    def get_max_pnl(self):
        return self.trade.pnl_max
        




