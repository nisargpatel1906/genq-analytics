import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { Button } from './Button';

describe('Button Component', () => {
  it('renders button with children', () => {
    render(<Button>Click Me</Button>);
    const buttonElement = screen.getByRole('button', { name: /click me/i });
    expect(buttonElement).toBeInTheDocument();
  });

  it('handles click events', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click Me</Button>);
    const buttonElement = screen.getByRole('button', { name: /click me/i });
    fireEvent.click(buttonElement);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('applies primary variant classes by default', () => {
    render(<Button>Primary</Button>);
    const buttonElement = screen.getByRole('button', { name: /primary/i });
    expect(buttonElement.className).toContain('bg-accent');
  });

  it('applies danger variant classes when specified', () => {
    render(<Button variant="danger">Danger</Button>);
    const buttonElement = screen.getByRole('button', { name: /danger/i });
    expect(buttonElement.className).toContain('bg-error');
  });
});
