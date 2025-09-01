#!/usr/bin/env python3
"""
Script to append GPX files that begin with numbers in numeric order.
Reads numbered GPX files (1_*, 2_*, etc.) and combines them into a single output file.
"""

import os
import re
from pathlib import Path
from typing import List, Tuple


def get_numbered_files(directory: str = ".") -> List[Tuple[int, str]]:
    """
    Get all files that start with a number, returning them as (number, filename) tuples.
    
    Args:
        directory: Directory to scan for files
        
    Returns:
        List of (number, filename) tuples sorted by number
    """
    numbered_files = []
    
    for filename in os.listdir(directory):
        # Match files that start with one or more digits followed by underscore or other character
        match = re.match(r'^(\d+)_.*\.gpx$', filename)
        if match:
            number = int(match.group(1))
            numbered_files.append((number, filename))
    
    # Sort by the numeric prefix
    numbered_files.sort(key=lambda x: x[0])
    return numbered_files


def append_gpx_files(output_filename: str = "combined_route.gpx", directory: str = ".") -> None:
    """
    Append numbered GPX files in numeric order to create a combined route file.
    
    Args:
        output_filename: Name of the output file
        directory: Directory containing the GPX files
    """
    numbered_files = get_numbered_files(directory)
    
    if not numbered_files:
        print("No numbered GPX files found.")
        return
    
    print(f"Found {len(numbered_files)} numbered GPX files:")
    for number, filename in numbered_files:
        print(f"  {number}: {filename}")
    
    output_path = Path(directory) / output_filename
    
    with open(output_path, 'w', encoding='utf-8') as output_file:
        for i, (number, filename) in enumerate(numbered_files):
            file_path = Path(directory) / filename
            print(f"Processing {filename}...")
            
            with open(file_path, 'r', encoding='utf-8') as input_file:
                content = input_file.read()
                
                if i == 0:
                    # For the first file, write everything
                    # Remove the closing </gpx> tag to keep it open
                    content = content.rstrip()
                    if content.endswith('</gpx>'):
                        content = content[:-6]
                    output_file.write(content)
                else:
                    # For subsequent files, extract only the track/route data
                    # Skip XML header and opening <gpx> tag, skip closing </gpx> tag
                    lines = content.split('\n')
                    in_track_data = False
                    
                    for line in lines:
                        # Start writing when we hit track or route data
                        if '<trk>' in line or '<rte>' in line:
                            in_track_data = True
                        
                        if in_track_data and not line.strip().startswith('<?xml') and not line.strip().startswith('<gpx'):
                            if not line.strip() == '</gpx>':
                                output_file.write(line + '\n')
                        
                        # Stop if we hit the end of track/route data
                        if '</trk>' in line or '</rte>' in line:
                            in_track_data = False
        
        # Close the GPX file
        output_file.write('</gpx>\n')
    
    print(f"\nCombined {len(numbered_files)} files into {output_filename}")


def main():
    """Main function to run the script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Append numbered GPX files in numeric order")
    parser.add_argument("-o", "--output", default="combined_route.gpx", 
                       help="Output filename (default: combined_route.gpx)")
    parser.add_argument("-d", "--directory", default=".", 
                       help="Directory containing GPX files (default: current directory)")
    parser.add_argument("--list", action="store_true", 
                       help="Just list the numbered files without processing")
    
    args = parser.parse_args()
    
    if args.list:
        numbered_files = get_numbered_files(args.directory)
        print(f"Found {len(numbered_files)} numbered GPX files in {args.directory}:")
        for number, filename in numbered_files:
            print(f"  {number}: {filename}")
    else:
        append_gpx_files(args.output, args.directory)


if __name__ == "__main__":
    main()