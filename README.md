
# Python FastAPI Backend with Secure Authentication and Profile Services



This repository contains a production-ready Python backend built using FastAPI. It includes essential security measures for authentication, protected routes, user registration, login, and fetching profile information services.

## Features

- User Registration: New users can sign up with a unique username and a strong password.
- User Login: Registered users can securely log in using their credentials.
- JWT Authentication: JSON Web Tokens (JWT) are used for secure authentication.
- Protected Routes: Certain routes are protected and require a valid JWT token to access.
- Profile Information: Authenticated users can fetch their profile information.

The code used MogoDB as the database & searches for a redis client over the network and connects it directly just turn on the redis client, you can update all the variables in .env file.
All Endpoints can be find within the main.py file, and you can start the app by uvicorn
