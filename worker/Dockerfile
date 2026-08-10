FROM python:3.11.15
WORKDIR /worker
COPY load_driver.py .
RUN pip install httpx==0.28.1
CMD ["python", "load_driver.py"]