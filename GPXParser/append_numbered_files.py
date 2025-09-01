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
    Append numbered GPX files in numeric order to create a single track segment.
    
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
    
    # Collect all track points from all files
    all_track_points = []
    gpx_header = None
    track_name = "Combined Route"
    
    for i, (number, filename) in enumerate(numbered_files):
        file_path = Path(directory) / filename
        print(f"Processing {filename}...")
        
        with open(file_path, 'r', encoding='utf-8') as input_file:
            content = input_file.read()
            lines = content.split('\n')
            
            if i == 0:
                # Extract GPX header from first file
                gpx_header_lines = []
                for line in lines:
                    if line.strip().startswith('<?xml') or line.strip().startswith('<gpx'):
                        gpx_header_lines.append(line)
                    elif '<trk>' in line:
                        break
                gpx_header = '\n'.join(gpx_header_lines)
            
            # Extract track points from this file
            in_trkseg = False
            in_trkpt = False
            current_trkpt = []
            
            for line in lines:
                if '<trkseg>' in line:
                    in_trkseg = True
                    continue
                elif '</trkseg>' in line:
                    in_trkseg = False
                    continue
                elif in_trkseg:
                    if '<trkpt' in line:
                        in_trkpt = True
                        current_trkpt = [line.strip()]
                    elif in_trkpt:
                        current_trkpt.append(line.strip())
                        if '</trkpt>' in line:
                            # Complete track point found, add it to collection
                            all_track_points.extend(current_trkpt)
                            current_trkpt = []
                            in_trkpt = False
    
    # Write the combined GPX file with single track segment
    with open(output_path, 'w', encoding='utf-8') as output_file:
        # Write GPX header
        output_file.write(gpx_header + '\n')
        
        # Write single track with all points
        output_file.write('  <trk>\n')
        output_file.write(f'    <name>{track_name}</name>\n')
        output_file.write('    <trkseg>\n')
        
        # Write all track points
        for point_line in all_track_points:
            output_file.write('      ' + point_line + '\n')
        
        output_file.write('    </trkseg>\n')
        output_file.write('  </trk>\n')
        output_file.write('</gpx>\n')
    
    print(f"\nCombined {len(numbered_files)} files into {output_filename} with {len(all_track_points)} track points")


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