import string

def concat(x, y):
    return f"{x}:{y}"

def caps(str):
    return string.capwords(str)

print(f"Welcome to my demo package\nconcat('Hello', 'world') produces {concat('Hello', 'world')}")