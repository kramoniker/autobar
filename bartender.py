
#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

#--------------Driver Library-----------------#
import OLED_Driver as OLED

import time
import sys
import RPi.GPIO as GPIO
import json
import traceback
import threading
import textwrap
import subprocess

from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
from PIL import ImageColor

from menu import MenuItem, Menu, Back, MenuContext, MenuDelegate
from drinks import drink_list, drink_options

GPIO.setmode(GPIO.BCM)

SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128

LEFT_BTN_PIN = 13
LEFT_PIN_BOUNCE = 200

RIGHT_BTN_PIN = 5
RIGHT_PIN_BOUNCE = 200

STATE_UNKNOWN       = "Unknown"
STATE_INITIALIZING  = "Initializing"
STATE_RUNNING       = "Running"
STATE_WAITING       = "Waiting..."
STATE_SLEEPING      = "Sleeping"
STATE_POURING       = "Pouring..."
STATE_POUR_FINISHED = "Enjoy your drink!"
STATE_CLEANING      = "Cleaning..."
STATE_SHUTDOWN      = "Please wait 10 seconds to power off"
SLEEP_TIMEOUT       = 30

machine_state         = STATE_INITIALIZING
prev_machine_state    = STATE_UNKNOWN
display_machine_state = STATE_UNKNOWN
start_time            = time.time()

NUMBER_NEOPIXELS = 45
NEOPIXEL_DATA_PIN = 26
NEOPIXEL_CLOCK_PIN = 6
NEOPIXEL_BRIGHTNESS = 64

FLOW_RATE = 60.0/500.0

# Raspberry Pi pin configuration:
RST = 14
# Note the following are only used with SPI:
DC = 15
SPI_PORT = 0
SPI_DEVICE = 0

#Fontsize and Font Type Settings
FONTSIZE = 15
FONTFILE = "cambriab.ttf"

#Wraps Text for better view on OLED screen. 13 is best for 128x64
WRAPPER = textwrap.TextWrapper(width=13)

class Bartender(MenuDelegate): 
	def __init__(self):
		self.machine_state = STATE_INITIALIZING
		self.display_machine_state = self.machine_state

		# set the oled screen height
		self.screen_width = SCREEN_WIDTH
		self.screen_height = SCREEN_HEIGHT

		self.btn1Pin = LEFT_BTN_PIN
		self.btn2Pin = RIGHT_BTN_PIN

		GPIO.setmode(GPIO.BCM)

	 	# configure interrups for buttons
		GPIO.setup(self.btn1Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.setup(self.btn2Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

		GPIO.add_event_detect(LEFT_BTN_PIN, GPIO.FALLING, callback=self.left_btn, bouncetime=100)
		GPIO.add_event_detect(RIGHT_BTN_PIN, GPIO.FALLING, callback=self.right_btn, bouncetime=100)

		# configure screen
		spi_bus = 0
		spi_device = 0

        #Load the display driver.
		OLED.Device_Init()
		self.image = Image.new("RGB", (self.screen_width, self.screen_height), "BLACK")
		self.draw = ImageDraw.Draw(self.image)
		self.font = ImageFont.truetype(FONTFILE ,FONTSIZE)

		# load the pump configuration from file
		self.pump_configuration = Bartender.readPumpConfiguration()
		for pump in self.pump_configuration.keys():
			GPIO.setup(self.pump_configuration[pump]["pin"], GPIO.OUT, initial=GPIO.HIGH)

		# setup pixels:
		print ("Done initializing")

		self.machine_state = STATE_WAITING
		self.display_machine_state = STATE_WAITING

	@staticmethod
	def readPumpConfiguration():
		return json.load(open('pump_config.json'))

	@staticmethod
	def writePumpConfiguration(configuration):
		with open("pump_config.json", "w") as jsonFile:
			json.dump(configuration, jsonFile)

	def startInterrupts(self):
		GPIO.add_event_detect(self.btn1Pin, GPIO.FALLING, callback=self.left_btn, bouncetime=LEFT_PIN_BOUNCE)  
		GPIO.add_event_detect(self.btn2Pin, GPIO.FALLING, callback=self.right_btn, bouncetime=RIGHT_PIN_BOUNCE)  

	def buildMenu(self, drink_list, drink_options):
		# create a new main menu
		m = Menu("Main Menu")

		# add drink options
		drink_opts = []
		for d in drink_list:
			drink_opts.append(MenuItem('drink', d["name"], {"ingredients": d["ingredients"]}))

		configuration_menu = Menu("Configure")

		# add pump configuration options
		pump_opts = []
		for p in sorted(self.pump_configuration.keys()):
			config = Menu(self.pump_configuration[p]["name"])
			# add fluid options for each pump
			for opt in drink_options:
				# star the selected option
				selected = "*" if opt["value"] == self.pump_configuration[p]["value"] else ""
				config.addOption(MenuItem('pump_selection', opt["name"], {"key": p, "value": opt["value"], "name": opt["name"]}))
			# add a back button so the user can return without modifying
			config.addOption(Back("Back"))
			config.setParent(configuration_menu)
			pump_opts.append(config)

		# add pump menus to the configuration menu
		configuration_menu.addOptions(pump_opts)
		# add a back button to the configuration menu
		configuration_menu.addOption(Back("Back"))
		# adds an option that cleans all pumps to the configuration menu
		configuration_menu.addOption(MenuItem('clean', 'Clean'))
		# adds an option that shuts down the rpi
		configuration_menu.addOption(MenuItem('shutdown', 'Shutdown'))

		configuration_menu.setParent(m)

		m.addOptions(drink_opts)
		m.addOption(configuration_menu)

		# create a menu context
		self.menuContext = MenuContext(m, self)

	def filterDrinks(self, menu):
		"""
		Removes any drinks that can't be handled by the pump configuration
		"""
		for i in menu.options:
			if (i.type == "drink"):
				i.visible = False
				ingredients = i.attributes["ingredients"]
				presentIng = 0
				for ing in ingredients.keys():
					for p in self.pump_configuration.keys():
						if (ing == self.pump_configuration[p]["value"]):
							presentIng += 1
				if (presentIng == len(ingredients.keys())): 
					i.visible = True
			elif (i.type == "menu"):
				self.filterDrinks(i)

	def selectConfigurations(self, menu):
		"""
		Adds a selection star to the pump configuration option
		"""
		for i in menu.options:
			if (i.type == "pump_selection"):
				key = i.attributes["key"]
				if (self.pump_configuration[key]["value"] == i.attributes["value"]):
					i.name = "%s %s" % (i.attributes["name"], "*")
				else:
					i.name = i.attributes["name"]
			elif (i.type == "menu"):
				self.selectConfigurations(i)

	def prepareForRender(self, menu):
		self.filterDrinks(menu)
		self.selectConfigurations(menu)
		return True

	def menuItemClicked(self, menuItem):
		if (menuItem.type == "drink"):
			self.makeDrink(menuItem.name, menuItem.attributes["ingredients"])
			return True
		elif(menuItem.type == "pump_selection"):
			self.pump_configuration[menuItem.attributes["key"]]["value"] = menuItem.attributes["value"]
			Bartender.writePumpConfiguration(self.pump_configuration)
			return True
		elif(menuItem.type == "clean"):
			self.clean()
			return True
		elif(menuItem.type == "shutdown"):
			self.shutdown()
			return True
		return False

	def clean(self):
		waitTime = 20
		pumpThreads = []

		# cancel any button presses while the drink is being made
		# self.stopInterrupts()
		self.machine_state = STATE_CLEANING
		self.display_machine_state = self.machine_state

		for pump in self.pump_configuration.keys():
			pump_t = threading.Thread(target=self.pour, args=(self.pump_configuration[pump]["pin"], waitTime))
			pumpThreads.append(pump_t)

		# start the pump threads
		for thread in pumpThreads:
			thread.start()

		# start the progress bar - something isn't right with the progress bar. it lasts sigificantly longer than the pumping
#		self.progressBar(waitTime)

		# wait for threads to finish
		for thread in pumpThreads:
			thread.join()

		# show the main menu
		self.menuContext.showMenu()

		# sleep for a couple seconds to make sure the interrupts don't get triggered
		time.sleep(2)

		self.machine_state = STATE_WAITING

	def shutdown(self):
		self.display_machine_state = STATE_SHUTDOWN
		self.displayMenuItem(menuItem)
		time.sleep(5)

		OLED.Clear_Screen()
		
		#Clean shutdown device
		subprocess.Popen(['shutdown','-h','now'])


	def displayMenuItem(self, menuItem):
		print (menuItem.name)
		self.draw.rectangle([0,0,self.screen_width,self.screen_height], fill="BLACK",)
		self.draw.text((0,12), menuItem.name, fill = "BLUE", font = self.font)
		self.draw.text((0,30), self.display_machine_state, fill = "ORANGE", font = self.font)
		OLED.Clear_Screen()
		OLED.Display_Image(self.image)

	def cycleLights(self):
		t = threading.currentThread()
		head  = 0               # Index of first 'on' pixel
		tail  = -10             # Index of last 'off' pixel
		color = 0xFF0000        # 'On' color (starts red)

		while getattr(t, "do_run", True):
			self.strip.setPixelColor(head, color) # Turn on 'head' pixel
			self.strip.setPixelColor(tail, 0)     # Turn off 'tail'
			self.strip.show()                     # Refresh strip
			time.sleep(1.0 / 50)             # Pause 20 milliseconds (~50 fps)

			head += 1                        # Advance head position
			if(head >= self.numpixels):           # Off end of strip?
				head    = 0              # Reset to start
				color >>= 8              # Red->green->blue->black
				if(color == 0): color = 0xFF0000 # If black, reset to red

			tail += 1                        # Advance tail position
			if(tail >= self.numpixels): tail = 0  # Off end? Reset

	def lightsEndingSequence(self):
		# make lights green
		for i in range(0, self.numpixels):
			self.strip.setPixelColor(i, 0xFF0000)
		self.strip.show()

		time.sleep(5)

		# turn lights off
		for i in range(0, self.numpixels):
			self.strip.setPixelColor(i, 0)
		self.strip.show() 

	def pour(self, pin, waitTime):
		GPIO.output(pin, GPIO.LOW)
		time.sleep(waitTime)
		GPIO.output(pin, GPIO.HIGH)

	def progressBar(self, waitTime):
		interval = waitTime / 100
		for x in range(1, 101):
			self.updateProgressBar(x, y=35)
			OLED.Display_Image(self.image)
			time.sleep(interval)

	def makeDrink(self, drink, ingredients):
		# cancel any button presses while the drink is being made
		# self.stopInterrupts()
		self.prev_machine_state = self.machine_state
		self.machine_state = STATE_POURING
		self.display_machine_state = self.machine_state

		# launch a thread to control lighting
#		lightsThread = threading.Thread(target=self.cycleLights)
#		lightsThread.start()

		# Parse the drink ingredients and spawn threads for pumps
		maxTime = 0
		pumpThreads = []
		for ing in ingredients.keys():
			for pump in self.pump_configuration.keys():
				if ing == self.pump_configuration[pump]["value"]:
					waitTime = ingredients[ing] * FLOW_RATE
					if (waitTime > maxTime):
						maxTime = waitTime
					pump_t = threading.Thread(target=self.pour, args=(self.pump_configuration[pump]["pin"], waitTime))
					pumpThreads.append(pump_t)

		# start the pump threads
		for thread in pumpThreads:
			thread.start()

		# start the progress bar
#		print("maxtime: " + str(maxTime))
#		self.progressBar(maxTime)
		self.menuContext.showMenu()

		# wait for threads to finish
		for thread in pumpThreads:
			thread.join()

		self.machine_state = STATE_POUR_FINISHED
		self.display_machine_state = self.machine_state

		self.menuContext.showMenu()

		time.sleep(2)

		self.machine_state = STATE_WAITING
		self.display_machine_state = self.machine_state

		# show the main menu
		#self.menuContext.showMenu()

		# stop the light thread
#		lightsThread.do_run = False
#		lightsThread.join()

		# show the ending sequence lights
#		self.lightsEndingSequence()

		# sleep for a couple seconds to make sure the interrupts don't get triggered
		#time.sleep(2);

		# reenable interrupts
		# self.startInterrupts()
		self.start_time    = time.time()

	def left_btn(self, ctx):
		if self.machine_state != STATE_RUNNING:
			self.prev_machine_state = self.machine_state
			self.machine_state = STATE_RUNNING
			self.display_machine_state = self.prev_machine_state
			self.start_time = time.time()
			if (self.prev_machine_state == STATE_SLEEPING):
				self.display_machine_state == STATE_WAITING
				self.menuContext.showMenu()
				print("LEFT button press woke from sleep")
			elif (self.prev_machine_state == STATE_WAITING):
				self.menuContext.advance()
				print("LEFT button press advanced menu")
			else:
				print("ignored LEFT button press")
		self.machine_state = STATE_WAITING
		self.prev_machine_state = STATE_WAITING
	
	def right_btn(self, ctx):
		if self.machine_state != STATE_RUNNING:
			self.prev_machine_state = self.machine_state
			self.machine_state = STATE_RUNNING
			self.display_machine_state = self.prev_machine_state
			self.start_time = time.time()
			if (self.prev_machine_state == STATE_SLEEPING):
				self.display_machine_state = STATE_WAITING
				self.menuContext.showMenu()
				print("RIGHT button press woke from sleep")
			elif (self.prev_machine_state == STATE_WAITING):
				self.menuContext.select()
				print("RIGHT button press selected menu item")
			else:
				print("ignored RIGHT button press")
		self.machine_state = STATE_WAITING
		self.prev_machine_state = STATE_WAITING

	def updateProgressBar(self, percent, x=15, y=15):
		height = 10
		width = self.screen_width-2*x
		for w in range(0, width):
			self.draw.point((w + x, y), fill=255)
			self.draw.point((w + x, y + height), fill=255)
		for h in range(0, height):
			self.draw.point((x, h + y), fill=255)
			self.draw.point((self.screen_width-x, h + y), fill=255)
			for p in range(0, percent):
				p_loc = int(p/100.0*width)
				self.draw.point((x + p_loc, h + y), fill=255)

	def run(self):
		self.start_time = time.time()
		
		# main loop
		try:

			while True:
				# disable OLED screen if no activity for SLEEP_TIMEOUT seconds to prevent burning out screen
				if ((time.time() - self.start_time) > SLEEP_TIMEOUT) and (self.machine_state != STATE_SLEEPING): 
					self.machine_state = STATE_SLEEPING
					self.display_machine_state = self.machine_state
					OLED.Clear_Screen()

		except KeyboardInterrupt:
			OLED.Clear_Screen()
			GPIO.cleanup()       # clean up GPIO on CTRL+C exit
		GPIO.cleanup()           # clean up GPIO on normal exit

		traceback.print_exc()


bartender = Bartender()
bartender.buildMenu(drink_list, drink_options)
bartender.run()
