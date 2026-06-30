import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import AppRoutes from './routes'

function KeyboardBackHandler() {
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.altKey &&
        (e.key === "ArrowLeft" || e.key === "Left")
      ) {
        e.preventDefault();
        navigate(-1);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate]);

  return null;
}

export default function App() {
  return (
    <>
      <KeyboardBackHandler />
      <AppRoutes />
    </>
  );
}
