# Use an official Python runtime as a base image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy only the requirements first to leverage Docker cache
COPY requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all other files
COPY . .

# Run your main bot file (replace 'bot.py' with your filename)
CMD ["python", "protectioniv.py"]
