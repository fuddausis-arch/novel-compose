import { useEffect, Component, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import AppRoutes from './routes'

class ErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '2rem', textAlign: 'center', color: '#ccc' }}>
          <h2>应用出错，请刷新页面</h2>
        </div>
      );
    }
    return this.props.children;
  }
}

function KeyboardBackHandler() {
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.altKey &&
        e.key === "ArrowLeft"
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
    <ErrorBoundary>
      <KeyboardBackHandler />
      <AppRoutes />
    </ErrorBoundary>
  );
}
