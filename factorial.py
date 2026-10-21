def factorial(n):
    if n < 0:
        raise ValueError("Факториал определен только для неотрицательных чисел")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result

if __name__ == "__main__":
    number = int(input("Введите число: "))
    print(factorial(number))
