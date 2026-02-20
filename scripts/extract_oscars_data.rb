#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
require 'open3'
require 'rexml/document'

XLSX_PATH = '/Users/mattod/Downloads/Oscar Nominations 2026 - MY COPY.xlsx'
OUTPUT_PATH = File.expand_path('../data/nominees.json', __dir__)

module XmlHelpers
  module_function

  def unzip_entry(xlsx_path, entry)
    stdout, status = Open3.capture2('unzip', '-p', xlsx_path, entry)
    raise "Failed to read #{entry}" unless status.success?

    stdout
  end

  def parse_xml(content)
    REXML::Document.new(content)
  end

  def text_value(cell, shared_strings)
    return nil if cell.nil?

    type = cell.attributes['t']
    value_node = cell.elements['v']
    return '' if value_node && value_node.text.to_s.empty?
    return nil unless value_node

    raw = value_node.text.to_s
    if type == 's'
      shared_strings[raw.to_i]
    else
      raw
    end
  end

  def cell_map(row)
    map = {}
    row.elements.each('c') { |c| map[c.attributes['r']] = c }
    map
  end
end

shared_strings_xml = XmlHelpers.unzip_entry(XLSX_PATH, 'xl/sharedStrings.xml')
shared_doc = XmlHelpers.parse_xml(shared_strings_xml)
shared_strings = []
shared_doc.elements.each('//sst/si') do |si|
  text = +''
  t_node = si.elements['t']
  if t_node
    text = t_node.text.to_s
  else
    runs = []
    si.elements.each('r') do |run|
      t = run.elements['t']
      runs << t.text.to_s if t
    end
    text = runs.join
  end
  shared_strings << text
end

sheet2_xml = XmlHelpers.unzip_entry(XLSX_PATH, 'xl/worksheets/sheet2.xml')
sheet2_doc = XmlHelpers.parse_xml(sheet2_xml)

films = {}
sheet2_doc.elements.each('//worksheet/sheetData/row') do |row|
  cells = XmlHelpers.cell_map(row)
  row_num = row.attributes['r'].to_i
  next if row_num == 1

  film_id = XmlHelpers.text_value(cells["A#{row_num}"], shared_strings)
  title = XmlHelpers.text_value(cells["B#{row_num}"], shared_strings)
  next if film_id.to_s.strip.empty?
  next if title.to_s.strip.empty?

  films[film_id] = {
    'id' => film_id,
    'title' => title,
    'availability' => {
      'free' => XmlHelpers.text_value(cells["C#{row_num}"], shared_strings).to_s.strip,
      'subscription' => XmlHelpers.text_value(cells["D#{row_num}"], shared_strings).to_s.strip,
      'rent' => XmlHelpers.text_value(cells["E#{row_num}"], shared_strings).to_s.strip,
      'theaters' => XmlHelpers.text_value(cells["F#{row_num}"], shared_strings).to_s.strip
    }
  }
end

sheet3_xml = XmlHelpers.unzip_entry(XLSX_PATH, 'xl/worksheets/sheet3.xml')
sheet3_doc = XmlHelpers.parse_xml(sheet3_xml)
category_years = {}
sheet3_doc.elements.each('//worksheet/sheetData/row') do |row|
  row_num = row.attributes['r'].to_i
  next if row_num == 1

  cells = XmlHelpers.cell_map(row)
  name = XmlHelpers.text_value(cells["A#{row_num}"], shared_strings).to_s.strip
  started = XmlHelpers.text_value(cells["B#{row_num}"], shared_strings).to_s.strip
  ended = XmlHelpers.text_value(cells["C#{row_num}"], shared_strings).to_s.strip
  next if name.empty?

  category_years[name] = {
    'yearStarted' => started.empty? ? nil : started.to_i,
    'yearEnded' => ended.empty? ? nil : ended.to_i
  }
end

sheet1_xml = XmlHelpers.unzip_entry(XLSX_PATH, 'xl/worksheets/sheet1.xml')
sheet1_doc = XmlHelpers.parse_xml(sheet1_xml)

nominations = []
seen_by_film = {}
category_order = []

sheet1_doc.elements.each('//worksheet/sheetData/row') do |row|
  row_num = row.attributes['r'].to_i
  next if row_num == 1

  cells = XmlHelpers.cell_map(row)
  category = XmlHelpers.text_value(cells["A#{row_num}"], shared_strings).to_s.strip
  nominee = XmlHelpers.text_value(cells["B#{row_num}"], shared_strings).to_s.strip
  film_id = XmlHelpers.text_value(cells["D#{row_num}"], shared_strings).to_s.strip
  seen_raw = XmlHelpers.text_value(cells["E#{row_num}"], shared_strings).to_s.strip

  next if film_id.empty?
  next if category.empty?

  category_order << category unless category_order.include?(category)

  nominations << {
    'category' => category,
    'nominee' => nominee,
    'filmId' => film_id
  }

  seen = (seen_raw == '1' || seen_raw.downcase == 'true')
  seen_by_film[film_id] = true if seen
end

films_in_nominations = nominations.map { |n| n['filmId'] }.uniq
filtered_films = films_in_nominations.map { |id| films[id] }.compact

categories = category_order.map do |name|
  {
    'name' => name,
    'yearStarted' => category_years.dig(name, 'yearStarted'),
    'yearEnded' => category_years.dig(name, 'yearEnded')
  }
end

output = {
  'schemaVersion' => 1,
  'years' => {
    '2026' => {
      'year' => 2026,
      'label' => '2026 Academy Awards Nominees',
      'categories' => categories,
      'films' => filtered_films,
      'nominations' => nominations,
      'defaultSeenFilmIds' => seen_by_film.keys.sort
    }
  }
}

File.write(OUTPUT_PATH, JSON.pretty_generate(output))

puts "Wrote #{OUTPUT_PATH}"
puts "Films: #{filtered_films.length}"
puts "Nominations: #{nominations.length}"
puts "Categories: #{categories.length}"
puts "Seen defaults: #{seen_by_film.keys.length}"
