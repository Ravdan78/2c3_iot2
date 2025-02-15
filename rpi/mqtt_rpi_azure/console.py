import socket
import paho.mqtt.publish as publish
from datetime import datetime
import json
import requests
import Adafruit_SSD1306
from PIL import Image, ImageDraw, ImageFont
import threading
import RPi.GPIO as GPIO
import time
import neopixel
import board

TRIGGER_PIN = 24
ECHO_PIN = 23

GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIGGER_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)

RPI_SERVER_IP = "0.0.0.0"
RPI_SERVER_PORT1 = 12345
RPI_SERVER_PORT2 = 22345
MQTT_BROKER = "74.234.16.173"
SHELLY1_IP = "172.20.10.3"

mq2_readings = []

# Initialize NeoPixel
pixel_pin = board.D10
num_pixels = 12
ORDER = neopixel.GRB
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=0.2, auto_write=False, pixel_order=ORDER)

# Initialize the OLED display
disp = Adafruit_SSD1306.SSD1306_128_64(rst=None, i2c_address=0x3C)
disp.begin()
disp.clear()
disp.display()

font = ImageFont.load_default()

THRESHOLD_DISTANCE = 10 


def read_distance():
    GPIO.output(TRIGGER_PIN, True)
    time.sleep(0.00001)
    GPIO.output(TRIGGER_PIN, False)
    
    start_time = time.time()
    stop_time = time.time()
    
    while GPIO.input(ECHO_PIN) == 0:
        start_time = time.time()
    
    while GPIO.input(ECHO_PIN) == 1:
        stop_time = time.time()
    
    elapsed_time = stop_time - start_time
    distance_cm = (elapsed_time * 34300) / 2
    
    return distance_cm
    
image = Image.new('1', (disp.width, disp.height))
draw = ImageDraw.Draw(image)

def turn_off_display():
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)
    disp.image(image)
    disp.display()

def display_text(lines):
    global draw 
    start_y_position = 10
    for i, line in enumerate(lines):
        y_position = start_y_position + i * 10
        draw.text((0, y_position), line, font=font, fill=255)
    disp.image(image)
    disp.display()

def display_sensor_info(distance, temperature, humidity):
    date_str = datetime.now().strftime("%d/%m/%Y")
    time_str = datetime.now().strftime("%H:%M")
    lines = [f"Date: {date_str}", f"Time: {time_str}", f"Temp: {temperature}°C", f"Hum: {humidity}%", f"Distance: {distance} cm"]
    display_text(lines)

def process_dht11_reading(sensor_data):
    print("Received DHT11 data:", sensor_data) 
    temperature = sensor_data.get('temperature')
    humidity = sensor_data.get('humidity')
    if temperature is not None and humidity is not None:
        print(f"Displaying temperature: {temperature}, humidity: {humidity}")
        date_str = datetime.now().strftime("%d/%m/%Y")
        time_str = datetime.now().strftime("%H:%M")
        lines = [f"Date: {date_str}", f"Time: {time_str}", f"Temp: {temperature}°C", f"Hum: {humidity}%"]
        display_text(lines)
        publish_to_mqtt(sensor_data)
    else:
        print("Missing temperature or humidity in DHT11 data")

def control_shelly_plug(turn_on):
    action = "on" if turn_on else "off"
    print(f"Turning Shelly Plug {'ON' if turn_on else 'OFF'}")
    try:
        requests.get(f"http://{SHELLY1_IP}/relay/0?turn={action}")
        publish_shelly_state(turn_on)
    except requests.exceptions.RequestException as e:
        print(f"HTTP request error: {e}")

def process_mq2_reading(reading):
    global mq2_readings
    mq2_readings.append(float(reading)) 
    mq2_readings = mq2_readings[-1:] 
    print(f"Processing MQ2 reading: {reading}")
    
    if all(value > 100 for value in mq2_readings):
        print("MQ2 above 100, turning Shelly Plug ON")
        control_shelly_plug(True) 
    elif any(value < 100 for value in mq2_readings):
        print("MQ2 below 100, turning Shelly Plug OFF")
        control_shelly_plug(False) 
    #publish_to_mqtt({"sensor_type": "mq2", "value": reading})
    mqtt_payload = {"mq2_value": reading}
    publish_to_mqtt({"sensor_type": "mq2", **mqtt_payload})


def publish_shelly_state(turn_on):
    action = "ON" if turn_on else "OFF"
    topic = "shelly1/state"
    payload = "1" if turn_on else "0" 
    publish.single(topic, payload, hostname=MQTT_BROKER)
    print(f"Published Shelly1 state to MQTT broker: {action}")


def publish_to_mqtt(sensor_data):
    sensor_type = sensor_data.get("sensor_type")
    if sensor_type:
        topic_prefix = "espair" if sensor_type in ['dht11', 'mq2', 'mq7', 'mq135'] else "espsafe"
        topic = f"{topic_prefix}/{sensor_type}"
        sensor_data["datetime"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        publish.single(topic, json.dumps(sensor_data), hostname=MQTT_BROKER)
        print(f"Published {sensor_type} data to MQTT broker: {topic}")
    else:
        print("Error: Sensor type missing in payload")

def tcp_server(port, process_function):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((RPI_SERVER_IP, port))
        s.listen()
        print(f"TCP server listening on port {port}...")
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_connection, args=(conn, addr, process_function)).start()

consecutive_zeros = 0 
consecutive_ones = 0  

def handle_connection(conn, addr, process_function):
    with conn:
        print(f"Connected to: {addr}")
        while True:
            data = conn.recv(1024)
            if not data:
                break
            print(f"Received data from {addr}: {data.decode()}")
            try:
                sensor_data = json.loads(data.decode())
                if sensor_data.get("sensor_type") == "mq2":
                    mq2_value = sensor_data.get("mq2_value")
                    if mq2_value is not None:
                        process_mq2_reading(mq2_value)
                    else:
                        print("MQ2 reading is missing in the data")
                elif sensor_data.get("sensor_type") == "dht11":
                    process_dht11_reading(sensor_data)

                elif sensor_data.get("sensor_type") == "pir":
                    if sensor_data.get("value") == 1:
                        consecutive_ones += 1
                        if consecutive_ones >= 10:
                            consecutive_ones = 0
                    else:
                        consecutive_ones = 0

                    if consecutive_ones < 10:
                        print("PIR sensor detected alert!")
                        
                        for _ in range(5):
                            pixels.fill((25, 0, 0)) 
                            pixels.show()
                            time.sleep(0.2)
                            pixels.fill((0, 0, 0)) 
                            pixels.show()
                            time.sleep(0.2)
                
                elif sensor_data.get("sensor_type") == "knust" and sensor_data.get("value") == 1:
                    print("Knust sensor detected alert!")
                    for _ in range(5):
                        pixels.fill((25, 0, 0)) 
                        pixels.show()
                        time.sleep(0.2)
                        pixels.fill((0, 0, 0))
                        pixels.show()
                        time.sleep(0.2)

                elif sensor_data.get("sensor_type") == "water" or sensor_data.get("sensor_type") == "flame":
                    if sensor_data.get("value") == 0:
                        consecutive_zeros += 1
                        if consecutive_zeros >= 20:
                            consecutive_zeros = 0
                    else:
                        consecutive_zeros = 0

                    if consecutive_zeros < 20:
                        if sensor_data.get("sensor_type") == "water":
                            print("Water sensor detected alert!")
                        elif sensor_data.get("sensor_type") == "flame":
                            print("Flame sensor detected alert!")
                        
                        for _ in range(5):
                            pixels.fill((25, 0, 0)) 
                            pixels.show()
                            time.sleep(0.2)
                            pixels.fill((0, 0, 0)) 
                            pixels.show()
                            time.sleep(0.2)

                else:
                    print(f"Received data for unknown sensor type: {sensor_data.get('sensor_type')}")
                    process_function(sensor_data)  # For other sensors, publish to MQTT
            except Exception as e:
                print(f"Error processing data from {addr}: {e}")


def start_tcp_server1():
    tcp_server(RPI_SERVER_PORT1, publish_to_mqtt)

def start_tcp_server2():
    tcp_server(RPI_SERVER_PORT2, publish_to_mqtt)

def main():
    threading.Thread(target=start_tcp_server1).start()
    threading.Thread(target=start_tcp_server2).start()

    try:
        while True:
            distance = read_distance()
            
            if distance <= 10:
                temperature, humidity = read_dht11_data()
                display_sensor_info(distance, temperature, humidity)
            else:
                turn_off_display()
                
            time.sleep(1)
    except KeyboardInterrupt:
        GPIO.cleanup()




if __name__ == "__main__":
    main()

