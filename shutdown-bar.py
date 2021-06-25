#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

import time

#--------------Driver Library-----------------#
import OLED_Driver as OLED

#--------------Image Draw Library ------------#
from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
from PIL import ImageColor

# screen details
SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128

#Fontsize and Font Type Settings
FONTSIZE = 15
FONTFILE = "cambriab.ttf"

class ShutdownBar():
	def __init__(self):
		OLED.Device_Init()
		self.image = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "BLACK")
		self.draw  = ImageDraw.Draw(self.image)
		self.font = ImageFont.truetype(FONTFILE, FONTSIZE)

	def shutdown(self):
		shutdowntext = "Shutdown takes 10 seconds. Bye!"
		self.draw.rectangle([0,0,SCREEN_WIDTH, SCREEN_HEIGHT], fill="BLACK",)
		self.draw.text((0,12), shutdowntext, fill = "BLUE", font = self.font)
		OLED.Clear_Screen()
		OLED.Display_Image(self.image)
		time.sleep(5)

		OLED.Clear_Screen()

shutdown = ShutdownBar()
shutdown.shutdown()
