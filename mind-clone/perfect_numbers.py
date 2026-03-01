"""
Perfect Number Checker

A perfect number is a positive integer that equals the sum of its proper divisors
(excluding itself). For example, 6 is perfect because: 1 + 2 + 3 = 6
"""


def is_perfect_number(n):
    """
    Check if a number is a perfect number.
    
    Args:
        n: A positive integer to check
        
    Returns:
        bool: True if n is a perfect number, False otherwise
        
    Examples:
        >>> is_perfect_number(6)
        True  # 1 + 2 + 3 = 6
        >>> is_perfect_number(28)
        True  # 1 + 2 + 4 + 7 + 14 = 28
        >>> is_perfect_number(12)
        False  # 1 + 2 + 3 + 4 + 6 = 16 != 12
    """
    if n < 2:
        return False
    
    # Find all proper divisors (divisors less than n)
    divisors = []
    for i in range(1, n):
        if n % i == 0:
            divisors.append(i)
    
    # Check if sum of divisors equals the number
    divisor_sum = sum(divisors)
    
    return divisor_sum == n


def find_perfect_divisors(n):
    """
    Find all proper divisors of a number and their sum.
    
    Args:
        n: A positive integer
        
    Returns:
        tuple: (list of divisors, sum of divisors)
    """
    if n < 1:
        return [], 0
    
    divisors = [i for i in range(1, n) if n % i == 0]
    return divisors, sum(divisors)


def main():
    """Test the perfect number checker with various inputs."""
    test_numbers = [6, 28, 12, 496]
    
    print("=" * 60)
    print("PERFECT NUMBER CHECKER")
    print("=" * 60)
    print("\nA perfect number equals the sum of its proper divisors.\n")
    
    for num in test_numbers:
        divisors, div_sum = find_perfect_divisors(num)
        is_perfect = is_perfect_number(num)
        
        print(f"Number: {num}")
        print(f"  Proper divisors: {divisors}")
        print(f"  Sum of divisors: {div_sum}")
        print(f"  Is perfect: {is_perfect}")
        
        if is_perfect:
            print(f"  [PASS] {num} = {' + '.join(map(str, divisors))}")
        else:
            print(f"  [FAIL] {num} != {div_sum}")
        print()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    perfect_numbers = [n for n in test_numbers if is_perfect_number(n)]
    print(f"Perfect numbers found: {perfect_numbers}")
    print(f"Non-perfect numbers: {[n for n in test_numbers if n not in perfect_numbers]}")


if __name__ == "__main__":
    main()
