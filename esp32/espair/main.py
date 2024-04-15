import socket
import json
from machine import Pin, ADC
import _thread
import time
import wifi
import dht
import network


dht11_sensor = dht.DHT11(Pin(18))
mq2 = ADC(Pin(33))
mq7 = ADC(Pin(35))
mq135 = ADC(Pin(32))

led_pin = Pin(14, Pin.OUT)

RPI_SERVER_IP = "172.20.10.4"
RPI_SERVER_PORT = 12345

def toggle_led(x):
    while True:
        led_pin.value(1)
        time.sleep(1)
        led_pin.value(0)
        time.sleep(x)

def send_data_to_rpi(data):
    retry_count = 0
    max_retries = 3
    success = False

    while retry_count < max_retries and not success:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((RPI_SERVER_IP, RPI_SERVER_PORT))
            s.send(data.encode())
            s.close()
            print(f"Data sent successfully to {RPI_SERVER_IP}:{RPI_SERVER_PORT}")
            success = True
        except OSError as e:
            retry_count += 1
            time.sleep(2)

    if not success:
        print("Failed to send data after retries")

def read_sensors():
    while True:
        mq2_value = mq2.read()
        send_data_to_rpi(json.dumps({"sensor_type": "mq2", "mq2_value": mq2_value}))
        print("mq2   ", mq2_value)

        mq7_value = mq7.read()
        send_data_to_rpi(json.dumps({"sensor_type": "mq7", "mq7_value": mq7_value}))
        print("mq7   ", mq7_value)

        mq135_value = mq135.read()
        send_data_to_rpi(json.dumps({"sensor_type": "mq135", "mq135_value": mq135_value}))
        print("mq135   ", mq135_value)

        dht11_sensor.measure()
        temp = dht11_sensor.temperature()
        hum = dht11_sensor.humidity()
        dht_data = {"sensor_type": "dht11", "temperature": temp, "humidity": hum}
        send_data_to_rpi(json.dumps(dht_data))
        print ("temp   ",temp)
        print ("humitidy   ", hum)

        time.sleep(5)


def main():
    _thread.start_new_thread(read_sensors, ())
    _thread.start_new_thread(toggle_led, (15,))

if __name__ == "__main__":
    main()



