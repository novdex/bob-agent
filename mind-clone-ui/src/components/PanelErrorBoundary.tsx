import { Component, type ErrorInfo, type ReactNode } from "react";

type PanelErrorBoundaryProps = {
  children: ReactNode;
};

type PanelErrorBoundaryState = {
  hasError: boolean;
  message: string;
};

export class PanelErrorBoundary extends Component<PanelErrorBoundaryProps, PanelErrorBoundaryState> {
  constructor(props: PanelErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: Error): PanelErrorBoundaryState {
    return { hasError: true, message: error.message || "Unexpected UI error." };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("PanelErrorBoundary", error, info.componentStack);
  }

  reset = () => {
    this.setState({ hasError: false, message: "" });
  };

  render() {
    if (this.state.hasError) {
      return (
        <section className="panel fatal">
          <h2>UI panel crashed</h2>
          <p className="error">{this.state.message || "Unexpected render error."}</p>
          <button onClick={this.reset}>Retry panel render</button>
        </section>
      );
    }
    return this.props.children;
  }
}
