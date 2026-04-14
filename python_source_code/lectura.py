

def lectura(file):

    with open(file,"r") as file:
        return str(file.readlines(0)[0])