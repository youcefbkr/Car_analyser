print("---MINI PROJECT---")


class Car :
    def __init__(self,brand,year,speed):
        self.brand = brand 
        self.year = year
        self.speed = speed

    def is_moving(self):
        return self.speed >0 
    
    def info(self):
        print(self.brand,self.year,self.speed )

filename = "car.txt"

try :
    file = open(filename,"r")
    lines = file.readlines()
    file.close()
except FileNotFoundError:
    print("file not found")
    exit()


car_list = []
for line in lines :
    parts = line.strip().split(",")
    brand = parts[0]
    year = int(parts[1])
    speed = int(parts[2])

    car = Car(brand,year,speed)
    car_list.append(car)


for car in car_list:
    car.info()


moving_count = 0 

for car in car_list:
    if car.is_moving():
        moving_count += 1 

print("moving count :",moving_count)

fastest = None 

for car in car_list:
    if fastest is None or fastest.speed < car.speed :
        fastest = car 

print("fastest car is ",fastest.brand , fastest.speed)


slowest = None 
for car in car_list:
    if slowest is None or slowest.speed > car.speed:
        slowest = car 

print("slowest car is :",slowest.brand, slowest.speed)

total = 0 

for car in car_list:
    total += car.speed 

print("total speed is :",total)

if car_list:
    average = total/len(car_list)
else:
    average = 0 

print("average is :",average)



print("the cars are not moving:")
for car in car_list:
    if not car.is_moving():
        car.info()