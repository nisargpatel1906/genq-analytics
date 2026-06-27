import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Badge } from './Badge';

describe('Badge Component', () => {
  it('renders badge with text content', () => {
    render(<Badge>Success Status</Badge>);
    const badgeElement = screen.getByText(/success status/i);
    expect(badgeElement).toBeInTheDocument();
  });

  it('renders correct styling classes based on variant', () => {
    const { rerender } = render(<Badge variant="success">Success</Badge>);
    expect(screen.getByText(/success/i).className).toContain('text-[#5C6E3E]');

    rerender(<Badge variant="error">Error</Badge>);
    expect(screen.getByText(/error/i).className).toContain('text-[#8B3A3A]');

    rerender(<Badge variant="warning">Warning</Badge>);
    expect(screen.getByText(/warning/i).className).toContain('text-[#B8860B]');
  });
});
