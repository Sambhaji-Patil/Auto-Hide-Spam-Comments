# Use the official Python base image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /github/workspace

# Copy your code into the container
COPY . /github/workspace

# Install dependencies
RUN pip install --no-cache-dir -r /github/workspace/requirements.txt

# Command to run the script
CMD ["python", "/github/workspace/spam_detector.py"]
