# Currency Converter Frontend

This is the React/Vite frontend for the Currency Converter project.

## Local development

Run `npm i` to install dependencies.

Run `npm run dev` to start the development server.

## Docker

Build the frontend image:

```bash
docker build -t currency-converter-frontend .
```

Run the container:

```bash
docker run --rm -p 5173:80 currency-converter-frontend
```

The app will be available at `http://localhost:5173`.
