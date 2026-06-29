import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
  title?: string;
  message?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-container">
          <AlertTriangle size={48} color="#f87171" />
          <h2>{this.props.title ?? 'Something went wrong'}</h2>
          <p>
            {this.props.message ?? 'The app hit an unexpected error. Reload to try again.'}
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="retry-btn"
          >
            Reload
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}