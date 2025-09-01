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


def get_numbered_files(directory: str = "inputs") -> List[Tuple[int, str]]:
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


def get_variant_files(directory: str = "inputs") -> List[str]:
    """
    Get all variant files that start with 'v' followed by a number.
    
    Args:
        directory: Directory to scan for files
        
    Returns:
        List of variant filenames sorted alphabetically
    """
    variant_files = []
    
    for filename in os.listdir(directory):
        # Match files that start with 'v' followed by number/letter combinations
        if re.match(r'^v\d+.*\.gpx$', filename):
            variant_files.append(filename)
    
    # Sort alphabetically for consistent ordering
    variant_files.sort()
    return variant_files


def append_gpx_files(output_filename: str = "combined_route.gpx", directory: str = "inputs") -> None:
    """
    Append numbered GPX files in numeric order to create a single track segment,
    and add variant files as separate overlay tracks.
    
    Args:
        output_filename: Name of the output file
        directory: Directory containing the GPX files
    """
    numbered_files = get_numbered_files(directory)
    variant_files = get_variant_files(directory)
    
    if not numbered_files:
        print("No numbered GPX files found.")
        return
    
    print(f"Found {len(numbered_files)} numbered GPX files:")
    for number, filename in numbered_files:
        print(f"  {number}: {filename}")
    
    print(f"Found {len(variant_files)} variant files:")
    for filename in variant_files:
        print(f"  {filename}")
    
    # Create a new GPX object
    combined_gpx = gpxpy.gpx.GPX()
    
    # Create the main combined track
    main_track = gpxpy.gpx.GPXTrack()
    main_track.name = "Main Route"
    combined_gpx.tracks.append(main_track)
    
    # Create a single track segment for the main route
    main_segment = gpxpy.gpx.GPXTrackSegment()
    main_track.segments.append(main_segment)
    
    total_main_points = 0
    
    # Process numbered files for main route
    for number, filename in numbered_files:
        file_path = Path(directory) / filename
        print(f"Processing main route: {filename}...")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as gpx_file:
                gpx = gpxpy.parse(gpx_file)
                
                # Extract all track points from all tracks and segments
                for track_item in gpx.tracks:
                    for segment_item in track_item.segments:
                        for point in segment_item.points:
                            main_segment.points.append(point)
                            total_main_points += 1
                            
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            continue
    
    # Process variant files as separate overlay tracks
    total_variant_points = 0
    processed_variants = 0
    
    for filename in variant_files:
        file_path = Path(directory) / filename
        print(f"Processing variant: {filename}...")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as gpx_file:
                gpx = gpxpy.parse(gpx_file)
                
                # Create a separate track for each variant
                variant_track = gpxpy.gpx.GPXTrack()
                # Extract a readable name from filename
                variant_name = filename.replace('.gpx', '').replace('_', ' ').title()
                variant_track.name = f"Variant: {variant_name}"
                
                # Copy all segments from the variant file
                for track_item in gpx.tracks:
                    for segment_item in track_item.segments:
                        new_segment = gpxpy.gpx.GPXTrackSegment()
                        for point in segment_item.points:
                            new_segment.points.append(point)
                            total_variant_points += 1
                        variant_track.segments.append(new_segment)
                
                if variant_track.segments:
                    combined_gpx.tracks.append(variant_track)
                    processed_variants += 1
                            
        except Exception as e:
            print(f"Error processing variant {filename}: {e}")
            continue
    
    # Ensure outputs directory exists and write the combined GPX file
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / output_filename
    with open(output_path, 'w', encoding='utf-8') as output_file:
        output_file.write(combined_gpx.to_xml())
    
    print(f"\nCombined {len(numbered_files)} main files ({total_main_points} points) and {processed_variants} variants ({total_variant_points} points) into outputs/{output_filename}")


def main():
    """Main function to run the script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Append numbered GPX files in numeric order")
    parser.add_argument("-o", "--output", default="combined_route.gpx", 
                       help="Output filename (default: combined_route.gpx, saved to outputs/)")
    parser.add_argument("-d", "--directory", default="inputs", 
                       help="Directory containing GPX files (default: inputs)")
    parser.add_argument("--list", action="store_true", 
                       help="Just list the numbered and variant files without processing")
    
    args = parser.parse_args()
    
    if args.list:
        numbered_files = get_numbered_files(args.directory)
        variant_files = get_variant_files(args.directory)
        print(f"Found {len(numbered_files)} numbered GPX files in {args.directory}:")
        for number, filename in numbered_files:
            print(f"  {number}: {filename}")
        print(f"Found {len(variant_files)} variant GPX files in {args.directory}:")
        for filename in variant_files:
            print(f"  {filename}")
    else:
        append_gpx_files(args.output, args.directory)


if __name__ == "__main__":
    main()