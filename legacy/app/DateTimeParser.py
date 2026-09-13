import re
from datetime import datetime, timedelta
from dateutil import parser

class TimeParser:
    """
    A class for parsing various time-related expressions and formats.

    This class provides methods to handle dates, time increments, and keyword-based time references, 
    particularly focusing on formats commonly used in meteorological centers.

    Attributes:
        None

    Methods:
        parse_date(date_str: str) -> datetime
            Parses a given date string into a datetime object.
            
            Args:
                date_str (str): The date string to parse.
            
            Returns:
                datetime: The parsed datetime object.

            Raises:
                ValueError: If the date_str format is invalid or not recognized.

            Example:
                >>> tp = TimeParser()
                >>> tp.parse_date("2024-01-08")
                datetime.datetime(2024, 1, 8, 0, 0)

        parse_time_increment(inc_str: str) -> timedelta
            Parses a time increment string into a timedelta object.

            Args:
                inc_str (str): The time increment string to parse.
            
            Returns:
                timedelta: The parsed timedelta object representing the increment.

            Raises:
                ValueError: If the inc_str format is invalid or not recognized.

            Example:
                >>> tp = TimeParser()
                >>> tp.parse_time_increment("1h")
                datetime.timedelta(hours=1)

    """

    def __init__(self):
        self.current_time = datetime.now()

    def parse_date(self, date_text):
        """
        Parse a date from various formats and return a datetime object.

        Args:
            date_text (str): The input text containing a date.

        Returns:
            datetime: A datetime object representing the parsed date.

        Raises:
            ValueError: If the input date text cannot be parsed into a valid date.
        """
        try:
            # First, try to use keyword_equivalents
            keyword_equivalents = self.map_keywords_to_dates()
            parsed_date = keyword_equivalents[date_text]
            return parsed_date
        except KeyError:
            try:
                # if that fails, try to use the custom parse_meteo_date function
                parsed_date = self.parse_meteo_date(date_text)
                return parsed_date
            except ValueError:
                try:
                    # If that fails, try using dateutil.parser.parse
                    parsed_date = parser.parse(date_text)
                    return parsed_date
                except ValueError:
                    raise ValueError("Invalid date format")

    def parse_meteo_date(self, text):
        """
        Parse a date from some formats used by meteorological centers and return a datetime object.

        Args:
            text (str): The input text containing a date.

        Returns:
            datetime: A datetime object representing the parsed date.

        Raises:
            ValueError: If the input date text cannot be parsed into a valid date.
        """
        date_formats = ["%Y","%Y%m","%Y%m%d","%Y%m%d%H","%Y%m%d%H%M","%Y%m%d%H%M%S"]

        for date_format in date_formats:
            try:
                date = datetime.strptime(text, date_format)
                return date
            except ValueError:
                pass

        raise ValueError("Invalid date format")

    def create_time_unit(self, unit, value):
        """
        Create a timedelta object for a specified time unit with a given value.
    
        Parameters:
        - unit (str): The time unit to create the timedelta for. It can be one of the following strings: 'days', 'hours', 'minutes', 'seconds'.
        - value (int): The numeric value to associate with the time unit.
    
        Returns:
        - timedelta: A timedelta object representing the specified time unit with the provided value.
    
        Example:
        >>> create_time_unit('days', 3)
        datetime.timedelta(days=3)
    
        This function allows you to create a timedelta object with a specified time unit (e.g., days, hours, minutes, seconds) and a numeric value. It is particularly useful for constructing dictionaries or data structures where you need to associate values with time units.
        """
        return timedelta(**{unit: int(value)})


    def calculate_time_increment(self, sign, value, unit):
        """
        Calculate a time increment as a timedelta.
    
        Args:
            sign (str): The sign of the increment ('+' for addition, '-' for subtraction).
            value (int): The value of the increment.
            unit (str): The unit of time (e.g., 'd' for days, 'h' for hours).
    
        Returns:
            timedelta: A timedelta representing the time increment.
    
        Raises:
            ValueError: If an invalid time unit is provided.
    
        Examples:
            >>> calculate_time_increment('+', 2, 'd')
            datetime.timedelta(days=2)
        """

        # Define a mapping of time unit abbreviations to their corresponding full names
        TIME_UNITS_MAPPING = {
            'd': 'days',
            'h': 'hours',
            'm': 'minutes',
            's': 'seconds',
        }
        
        # Check if the provided time unit abbreviation is valid
        if unit in TIME_UNITS_MAPPING:
            # Retrieve the full name of the time unit
            time_unit = TIME_UNITS_MAPPING[unit]
        
            # Create a timedelta object for the specified time unit and value
            delta_time = self.create_time_unit(time_unit, value)
        else:
            # Raise a ValueError for an invalid time unit
            raise ValueError(f"Invalid time unit: {unit}")
        
        # Determine the delta value based on the provided sign
        delta_value = delta_time if sign == '+' else -delta_time
        
        # Return the resulting delta value
        return delta_value

            
    def parse_expression(self, expression):
        """
        Parse a time expression with optional components (days, hours, minutes, seconds) and return the parsed values as a timedelta.

        Args:
            expression (str): A time expression in the format: [name][sign][days][hours][minutes][seconds]

        Returns:
            timedelta or None: A timedelta representing the parsed time increment, or None if the expression is invalid.
        """

        # Define a regular expression pattern to parse the string
        # The pattern is designed to match and capture the following components:
        # - (?P<name>[A-Za-z0-9_]+): Captures a name consisting of alphanumeric characters and underscores. This part is optional.
        # - (?P<sign>[+-])?: Captures an optional sign indicating addition ('+') or subtraction ('-').
        # - ((?P<days>\d+d)?((?P<hours>\d+h)?((?P<minutes>\d+m)?((?P<seconds>\d+s)?)?)?)?)?: Captures optional components for days, hours, minutes, and seconds.
        #   - Each component is represented by a number followed by a unit identifier (d for days, h for hours, m for minutes, s for seconds).
        #   - The components can be combined in any order and are all optional.
        #   - For example, valid matches include '10d5h30m19s', '5h30m', '1d', '30m', and '19s'.
        pattern = r'(?P<name>[A-Za-z0-9_]+)(?P<sign>[+-])?((?P<days>\d+d)?((?P<hours>\d+h)?((?P<minutes>\d+m)?((?P<seconds>\d+s)?)?)?)?)?'

        expression = str(expression)  # Convert to string

        match = re.match(pattern, expression)

        if match:
            sign = match.group('sign')
            components = {
                'd': int(match.group('days')[:-1]) if match.group('days') else 0,
                'h': int(match.group('hours')[:-1]) if match.group('hours') else 0,
                'm': int(match.group('minutes')[:-1]) if match.group('minutes') else 0,
                's': int(match.group('seconds')[:-1]) if match.group('seconds') else 0
            }

            total_increment = timedelta()
            for unit, value in components.items():
                total_increment += self.calculate_time_increment(sign, value, unit)

            name = match.group('name')
            date = self.parse_date(name)
            total_time = date + total_increment

            return total_time
        else:
            return None

    def map_keywords_to_dates(self):
        current_time = self.current_time
        keyword_equivalents = {
            'today': current_time,
            'tomorrow': current_time + timedelta(days=1),
            'yesterday': current_time - timedelta(days=1),
            'now': current_time,
            'start_of_month': current_time.replace(day=1),
            'end_of_month': (current_time.replace(day=1, month=current_time.month % 12 + 1) - timedelta(days=1)),
            'start_of_year': current_time.replace(day=1, month=1),
            'end_of_year': current_time.replace(day=31, month=12),
            'next_week': current_time + timedelta(weeks=1),
            'last_week': current_time - timedelta(weeks=1),
            'beginning_of_next_month': current_time.replace(day=1, month=current_time.month % 12 + 1),
            'end_of_next_month': (current_time.replace(day=1, month=current_time.month % 12 + 1, year=current_time.year + (current_time.month // 12)) - timedelta(days=1)),
        }
        return keyword_equivalents

    def parse_time_expression(self,expression):
        """
        Parse a time expression and return a tuple containing the sign, value, and unit.
    
        Args:
            expression (str): The time expression to parse.
    
        Returns:
            tuple: A tuple containing the sign ('+' or '-'), the value as a string, and the unit (e.g., 'd', 'h', 'm', 's').
    
        Raises:
            ValueError: If the expression cannot be parsed.
    
        Examples:
            >>> parse_time_expression('+20d')
            ('+', '20', 'd')
            >>> parse_time_expression('-1h')
            ('-', '1', 'h')
            >>> parse_time_expression('30m')
            ('+', '30', 'm')
        """

        expression = str(expression)  # Convert to string
        
        pattern = r'(?P<sign>[+-]?)(?P<value>\d+)(?P<unit>[dhms]?)'
        match = re.match(pattern, expression)
    
        if match:
            sign = match.group('sign') if match.group('sign') else '+'
            value = match.group('value')
            unit = match.group('unit') if match.group('unit') else 's'  # Default to seconds if unit is not specified
    
            
            return self.calculate_time_increment(sign, value, unit)
        else:
            raise ValueError("Invalid time expression")

