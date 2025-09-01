#!/usr/bin/env python3
"""
Script to append GPX files that begin with numbers in numeric order.
Reads numbered GPX files (1_*, 2_*, etc.) and combines them into a single output file.
Uses gpxpy library for proper GPX handling.
"""

import os
import re
from pathlib import Path
from typing import List, Tuple
import gpxpy
import gpxpy.gpx


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
    
    # Create a new GPX object
    combined_gpx = gpxpy.gpx.GPX()
    
    # Create a single track
    track = gpxpy.gpx.GPXTrack()
    track.name = "Combined Route"
    combined_gpx.tracks.append(track)
    
    # Create a single track segment
    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)
    
    total_points = 0
    
    for number, filename in numbered_files:
        file_path = Path(directory) / filename
        print(f"Processing {filename}...")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as gpx_file:
                gpx = gpxpy.parse(gpx_file)
                
                # Extract all track points from all tracks and segments
                for track_item in gpx.tracks:
                    for segment_item in track_item.segments:
                        for point in segment_item.points:
                            segment.points.append(point)
                            total_points += 1
                            
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            continue
    
    # Write the combined GPX file
    output_path = Path(directory) / output_filename
    with open(output_path, 'w', encoding='utf-8') as output_file:
        output_file.write(combined_gpx.to_xml())
    
    print(f"\nCombined {len(numbered_files)} files into {output_filename} with {total_points} track points")


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